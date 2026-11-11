import random
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby

from .catalog import Catalog
from .config import Config
from .reference import FEE_CONFIG, SOURCE_FEE_TYPES

_FEEABLE_STATUSES = ("pending", "shipped", "delivered")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal(value: str) -> Decimal:
    return Decimal(str(value))


def to_usd(amount: Decimal, currency: str, cfg: Config) -> Decimal:
    rate = Decimal(str(cfg.fx_rates[currency]))
    return _money(amount * rate)


def to_local(usd: Decimal, currency: str, cfg: Config) -> Decimal:
    rate = Decimal(str(cfg.fx_rates[currency]))
    return _money(usd / rate)


# ------------------------------------------------------------
# FEE CALCULATION HELPERS
# ------------------------------------------------------------


def _product_index(catalog: Catalog) -> dict[str, tuple[str, Decimal]]:
    """
    Map each `product_id` to its category name and supplier cost.

    - One map keyed by `product_id`, holding the `CATEGORIES_LIST` category name
      used by `percent_by_category` and the `base_cost` used by fee tiers.
    """
    category_name = {cat.id: cat.name for cat in catalog.categories}

    return {
        prod.id: (category_name[prod.category_id], prod.base_cost)
        for prod in catalog.products
    }


def _lines_by_order(orders: list[dict]) -> dict[str, list[dict]]:
    """Group order lines by `order_id`, keeping generation order."""
    lines = (row for row in orders if "order_line_id" in row)
    return {
        key: list(group)
        for key, group in groupby(lines, key=lambda row: row["order_id"])
    }


def _percent(rule: dict, category: str | None) -> Decimal:
    by_category = rule.get("percent_by_category")
    if by_category is None:
        return _decimal(rule["percent"])

    return _decimal(by_category[category])


def _flat_charge(rule: dict, base_cost: Decimal) -> Decimal:
    """Return the flat charge of one fee rule."""

    # Fall back to fixed charge if not amazon channel
    tiers = rule.get("tiers")
    if not tiers:
        return _decimal(rule["fixed"])

    # Resolve amazon cost tiers
    # The first tier whose `max_base_cost` covers the cost wins. `None` bound matches every remaining cost.
    for tier in tiers:
        limit = tier["max_base_cost"]
        if limit is None or base_cost <= _decimal(limit):
            return _decimal(tier["fixed"])

    raise ValueError(f"no fee tier covers base cost {base_cost}")


def _fee_amount(
    rule: dict,
    gross: Decimal,
    units: int,
    percent: Decimal,
    flat_charge: Decimal,
) -> Decimal:
    """
    Return one fee: percent of `gross`, plus `flat_charge`, never below the minimum.

    - `units` is the line quantity, or 1 for order fees. Multiply `flat_charge`
        and `minimum` only when `rule["per_unit"]`, because `gross` already includes
        the quantity.
    - `minimum` is compared after the `flat_charge` is added, so it bounds the total.
    """

    multiplier = units if rule["per_unit"] else 1
    amount = gross * percent / 100
    amount += flat_charge * multiplier

    floor = _decimal(rule["minimum"]) * multiplier
    if amount < floor:
        amount = floor

    return _money(amount)


def _line_fee_amount(
    rule: dict,
    gross: Decimal,
    units: int,
    category: str,
    base_cost: Decimal,
) -> Decimal:
    """Return one line fee, resolving the category rate and the cost tier flat charge."""

    return _fee_amount(
        rule=rule,
        gross=gross,
        units=units,
        percent=_percent(rule, category),
        flat_charge=_flat_charge(rule, base_cost),
    )


def _order_fee_amount(rule: dict, gross: Decimal) -> Decimal:
    """Return one order fee, which has no line, no category, and no tier."""
    return _fee_amount(rule, gross, 1, _percent(rule, None), _decimal(rule["fixed"]))


# ------------------------------------------------------------
# FEE IDENTIFIERS AND ROWS
# ------------------------------------------------------------


def _fee_id(order_id: str, line_id: str | None, fee_type: str) -> str:
    """Build a fee key from its order, optional line, and fee type."""
    if line_id is None:
        return f"fee_{order_id}_{fee_type}"

    return f"fee_{line_id.replace('-', '_')}_{fee_type}"


def _defect_currency(cfg: Config, channel: str) -> str | None:
    """Return a relabelled store channel's currency."""
    others = [ch for ch in sorted(cfg.store_channels) if ch != channel]
    # 'None' so _fee_row 'is_defect' skips instead of relabelling w/ its own currency
    if not others:
        return None

    return cfg.channel_currency[others[0]]


def _fee_row(
    cfg: Config,
    rng: random.Random,
    header: dict,
    line_id: str | None,
    fee_type: str,
    source_fee_type: str,
    amount: Decimal,
    defect_currency: str | None,
    posted_at: datetime,
) -> dict:
    """Assemble one fee row and draw its currency defect from the order RNG."""

    is_defect = (
        rng.random() < cfg.fee_currency_defect_rate and defect_currency is not None
    )

    return {
        "fee_id": _fee_id(header["order_id"], line_id, fee_type),
        "channel": header["channel"],
        "order_id": header["order_id"],
        "order_line_id": line_id,
        "fee_type": fee_type,
        "source_fee_type": source_fee_type,
        "amount": amount,
        "currency": defect_currency if is_defect else header["currency"],
        "charged_at": posted_at,
        "updated_at": posted_at,
        "is_currency_defect": is_defect,
    }


def _posted_at(cfg: Config, header: dict, rng: random.Random) -> datetime:
    """Return when one order's fees posted."""

    low, high = cfg.channel_fee_lag_days[header["channel"]]
    posted_at = header["placed_at"] + timedelta(days=rng.randint(low, high))
    clamp_end_date = datetime.combine(cfg.end_date, time.max, tzinfo=timezone.utc)

    return min(posted_at, clamp_end_date)


# ------------------------------------------------------------
# GENERATE FEES
# ------------------------------------------------------------


def generate_fees(
    cfg: Config,
    catalog: Catalog,
    orders: list[dict],
) -> list[dict]:
    """
    Return one fee row per applicable `FEE_CONFIG` entry of every billable order.

    Workflow:
    - Initialize: index `catalog` by product for category and supplier cost, and
        group the flat `orders` rows into headers and lines.
    - Delegate: skip cancelled orders, then walk each channel's fee types in name
        order so the flagged-defect draw order stays stable.
    - Transform: charge an `order` scoped rule once on the header gross, and a
        `line` scoped rule once per line on the line gross.
    - Enrich: copy the order timestamps and channel currency, then relabel a
        bounded share of rows into another channel currency.

    Expectations:
    - Every `cfg.store_channels` entry is keyed in `FEE_CONFIG`.
    - `catalog` resolves the category and `base_cost` of every line `product_id`,
        because both category rates and cost tiers are read from it.

    Returns:
    - Rows are ordered by header, then fee type name, then line.
    - `order_line_id` is `None` on `order` scoped fees.
    - An orphan line has no catalog product, so it emits no fee row at all.

    Failures:
    - Finding: A channel missing from `FEE_CONFIG` raises `ValueError` instead
        of silently generating a channel with zero fees.
    """
    category_index = _product_index(catalog)
    lines_by_order = _lines_by_order(orders)

    fees: list[dict] = []
    for header in orders:
        if "placed_at" not in header:
            continue
        if header["status"] not in _FEEABLE_STATUSES:
            continue

        channel = header["channel"]
        if channel not in FEE_CONFIG:
            raise ValueError(f"no fee schedule for channel '{channel}'")

        order_rng = random.Random(f"{cfg.seed}:fees:{header['order_id']}")
        defect_currency = _defect_currency(cfg, channel)
        posted_at = _posted_at(cfg, header, order_rng)

        for fee_type in sorted(FEE_CONFIG[channel]):
            rule = FEE_CONFIG[channel][fee_type]
            source_fee_type = SOURCE_FEE_TYPES[channel][fee_type]

            if rule["scope"] == "order":
                amount = _order_fee_amount(rule, header["gross_amount"])
                fees.append(
                    _fee_row(
                        cfg=cfg,
                        rng=order_rng,
                        header=header,
                        line_id=None,
                        fee_type=fee_type,
                        source_fee_type=source_fee_type,
                        amount=amount,
                        defect_currency=defect_currency,
                        posted_at=posted_at,
                    )
                )
                continue

            for line in lines_by_order.get(header["order_id"], ()):
                product_id = line["product_id"]
                if product_id not in category_index:
                    continue

                category, base_cost = category_index[product_id]
                amount = _line_fee_amount(
                    rule=rule,
                    gross=line["gross_amount"],
                    units=line["quantity"],
                    category=category,
                    base_cost=base_cost,
                )
                fees.append(
                    _fee_row(
                        cfg=cfg,
                        rng=order_rng,
                        header=header,
                        line_id=line["order_line_id"],
                        fee_type=fee_type,
                        source_fee_type=source_fee_type,
                        amount=amount,
                        defect_currency=defect_currency,
                        posted_at=posted_at,
                    )
                )

    return fees


def generate_refunds():
    # TODO: Refunded lines, partial/full, refund date after the order, Small set of orphan refunds
    ...


def generate_ad_spends():
    # TODO: Amazon listings: per day RNG, impressions -> clicks -> spend
    ...


def generate_service_fees():
    # TODO: Amazon service fee per day RNG, mixed order scoped, account level e.g. Subscrption/storage fee
    ...
