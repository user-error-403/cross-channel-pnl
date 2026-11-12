import random
from datetime import datetime, timedelta
from decimal import Decimal

from .catalog import Catalog
from .config import Config
from .money_utils import (
    lines_by_order,
    money,
    to_decimal,
    window_end,
    wrong_currency,
)
from .reference import FEE_CONFIG, SOURCE_FEE_TYPES

_FEEABLE_STATUSES = ("pending", "shipped", "delivered")


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


def _percent(rule: dict, category: str | None) -> Decimal:
    by_category = rule.get("percent_by_category")
    if by_category is None:
        return to_decimal(rule["percent"])

    return to_decimal(by_category[category])


def _flat_charge(rule: dict, base_cost: Decimal) -> Decimal:
    """Return the flat charge of one fee rule."""

    # Fall back to fixed charge if not amazon channel
    tiers = rule.get("tiers")
    if not tiers:
        return to_decimal(rule["fixed"])

    # Resolve amazon cost tiers
    # The first tier whose `max_base_cost` covers the cost wins. `None` bound matches every remaining cost.
    for tier in tiers:
        limit = tier["max_base_cost"]
        if limit is None or base_cost <= to_decimal(limit):
            return to_decimal(tier["fixed"])

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

    floor = to_decimal(rule["minimum"]) * multiplier
    if amount < floor:
        amount = floor

    return money(amount)


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
    """Return one order fee, for no line, no category, and no tier."""
    return _fee_amount(
        rule=rule,
        gross=gross,
        units=1,
        percent=_percent(rule, None),
        flat_charge=to_decimal(rule["fixed"]),
    )


# ------------------------------------------------------------
# FEE IDENTIFIERS AND ROWS
# ------------------------------------------------------------


def _fee_id(order_id: str, line_id: str | None, fee_type: str) -> str:
    """Build a fee key from its order, optional line, and fee type."""
    if line_id is None:
        return f"fee_{order_id}_{fee_type}"

    return f"fee_{line_id.replace('-', '_')}_{fee_type}"


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

    return min(posted_at, window_end(cfg))


# ------------------------------------------------------------
# GENERATE FEES
# ------------------------------------------------------------


def generate_fees(
    cfg: Config,
    catalog: Catalog,
    orders: list[dict],
) -> list[dict]:
    """
    Return one fee row per applicable `FEE_CONFIG` rule of every billable order.

    One `random.Random` per order feeds its posted timestamp and every fee row
    of that order. A row's defect draw therefore depends on how many rows came
    before it, and sorted fee type names fix that sequence.

    Expectations:
    - Every `cfg.store_channels` entry is keyed in `FEE_CONFIG`,
      `SOURCE_FEE_TYPES`, and `channel_fee_lag_days`.
    - A line-scope rule skips a line whose `product_id` does not resolve in
      `catalog`, so an orphan line pays the order-scope fees only.

    Returns:
    - A defect order still emits clean rows, because `is_currency_defect` needs
      both the order draw and the row draw.
    - Rows come out ordered by order header, then fee type name, then line.
    """
    category_index = _product_index(catalog)
    order_lines = lines_by_order(orders)

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
        defect_currency = wrong_currency(cfg, channel)
        posted_at = _posted_at(cfg, header, order_rng)

        for fee_type in sorted(FEE_CONFIG[channel]):
            rule = FEE_CONFIG[channel][fee_type]
            source_fee_type = SOURCE_FEE_TYPES[channel][fee_type]

            # One charge on the header gross amount, using fixed rule data
            # So an order whose 'Line IDs' are all orphans still pays it.
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

            # One charge per order line, once per line-scope rule
            # Applies catalog category rate and cost tier.
            # A null 'product_id' is an orphan order line -> Skip
            for line in order_lines.get(header["order_id"], ()):
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
