import random
from datetime import datetime, timedelta
from decimal import Decimal

from .catalog import Catalog
from .config import Config
from .money_utils import lines_by_order, money, to_decimal, window_end
from .reference import REFUND_CONFIG, REFUND_REASONS

_REFUNDABLE_STATUSES = ("shipped", "delivered")


# ------------------------------------------------------------
# REFUND CALCULATION HELPERS
# ------------------------------------------------------------


def _category_index(catalog: Catalog) -> dict[str, str]:
    """
    Map each `product_id` to its `CATEGORIES_LIST` category name.

    - One map keyed by `product_id`, because `REFUND_CONFIG` sets the rate and
      partial share per category, not per product.
    """
    category_name = {cat.id: cat.name for cat in catalog.categories}

    return {prod.id: category_name[prod.category_id] for prod in catalog.products}


def _refund_amount(
    cfg: Config,
    line: dict,
    is_partial: bool,
    rng: random.Random,
) -> tuple[Decimal, bool]:
    """
    Return one refund amount and whether it is partial.

    - A partial refund draws a share of the line gross before rounding, so it
      stays below the full amount.
    - `is_partial` is re-derived from the rounded amount, never trusted from the
      draw, so the flag and the money can never disagree.
    """
    gross = line["gross_amount"]

    # Full refund
    if not is_partial:
        return gross, False

    low, high = cfg.partial_refund_pct_range
    amount = money(gross * Decimal(str(rng.uniform(low, high))))

    return amount, amount < gross


def _refunded_at(cfg: Config, placed_at: datetime, rng: random.Random) -> datetime:
    """Return when one refund lands, clamped to the end of the run window."""
    low, high = cfg.refund_window_days
    refunded_at = placed_at + timedelta(days=rng.randint(low, high))

    return min(refunded_at, window_end(cfg))


# ------------------------------------------------------------
# REFUND IDENTIFIERS AND ROWS
# ------------------------------------------------------------


def _orphan_order_id(order_id: str) -> str:
    """
    Shift one order's sequence out of the generated range.

    - Real sequences stay under 90000, so a shifted id never matches an order
      header and the orphan is detectable by a join.
    """
    prefix, seq = order_id.rsplit("_", 1)

    return f"{prefix}_{int(seq) + 90_000:05d}"


def _refund_id(line_id: str) -> str:
    """Build a refund key from its order line, which stays unique on orphans."""
    return f"refund_{line_id.replace('-', '_')}"


def _refund_row(
    header: dict,
    line: dict,
    amount: Decimal,
    is_partial: bool,
    reason: str,
    refunded_at: datetime,
    is_orphan: bool,
) -> dict:
    """Assemble one refund row, rewriting the keys of an orphan defect."""

    return {
        "refund_id": _refund_id(line["order_line_id"]),
        "channel": header["channel"],
        "order_id": (
            _orphan_order_id(header["order_id"]) if is_orphan else header["order_id"]
        ),
        "order_line_id": None if is_orphan else line["order_line_id"],
        "amount": amount,
        "currency": header["currency"],
        "reason": reason,
        "refunded_at": refunded_at,
        "updated_at": refunded_at,
        "is_partial": is_partial,
        "is_orphan": is_orphan,
    }


# ------------------------------------------------------------
# GENERATE REFUNDS
# ------------------------------------------------------------


def generate_refunds(
    cfg: Config,
    catalog: Catalog,
    orders: list[dict],
) -> list[dict]:
    """
    Return one refund row per refunded `shipped` or `delivered` order line.

    One `random.Random` per line keeps a line's refund independent of its
    neighbours. A full refund draws no share, so only the lag draw starts one
    step earlier in the line sequence.

    Expectations:
    - Every `CATEGORIES_LIST` name is keyed in `REFUND_CONFIG`, because the
      line's category selects both the refund rate and the partial share.
    - An orphan line has a `None` `product_id`, so it emits no refund row.

    Returns:
    - `is_partial` is `True` exactly when the amount is below the line
      `gross_amount`, never the raw share draw.
    - Rows come out ordered by order header, then line.
    """
    category_index = _category_index(catalog)
    order_lines = lines_by_order(orders)

    refunds: list[dict] = []
    for header in orders:
        if "placed_at" not in header:
            continue
        if header["status"] not in _REFUNDABLE_STATUSES:
            continue

        for line in order_lines.get(header["order_id"], ()):
            product_id = line["product_id"]
            if product_id not in category_index:
                continue

            rule = REFUND_CONFIG[category_index[product_id]]
            line_rng = random.Random(f"{cfg.seed}:refunds:{line['order_line_id']}")

            # Inject refund requests
            if line_rng.random() >= float(to_decimal(rule["rate"])):
                continue

            # Inject partial refund share
            # Orphan refund (keys point to nothing)
            is_partial = line_rng.random() < float(to_decimal(rule["partial_share"]))
            is_orphan = line_rng.random() < cfg.orphan_refund_rate
            reason = line_rng.choice(REFUND_REASONS)

            amount, is_partial = _refund_amount(cfg, line, is_partial, line_rng)
            refunded_at = _refunded_at(cfg, header["placed_at"], line_rng)

            refunds.append(
                _refund_row(
                    header=header,
                    line=line,
                    amount=amount,
                    is_partial=is_partial,
                    reason=reason,
                    refunded_at=refunded_at,
                    is_orphan=is_orphan,
                )
            )

    return refunds
