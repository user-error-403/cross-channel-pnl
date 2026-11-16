from datetime import datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby

from .config import Config


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def wrong_currency(cfg: Config, channel: str) -> str | None:
    """Return a relabelled store channel's currency."""
    others = [ch for ch in sorted(cfg.store_channels) if ch != channel]
    if not others:
        return None

    return cfg.channel_currency[others[0]]


def window_end(cfg: Config) -> datetime:
    """Return the last instant of the run window, in UTC."""
    return datetime.combine(cfg.end_date, time.max, tzinfo=timezone.utc)


def lines_by_order(orders: list[dict]) -> dict[str, list[dict]]:
    """Group order lines by `order_id`, keeping generation order."""
    lines = (row for row in orders if "order_line_id" in row)
    return {
        key: list(group) for key, group in groupby(lines, key=lambda r: r["order_id"])
    }
