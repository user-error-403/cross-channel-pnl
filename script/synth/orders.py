import random
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP

from .catalog import Catalog
from .clock import SimClock
from .config import Config
from .listing import Listing
from .seeding import stage_faker

# ------------------------------------------------------------
# SEASONALITY CONSTANTS AND HELPER FUNCTIONS
# ------------------------------------------------------------

_MONEY = Decimal("0.01")
# Mon to Sun: values in days order
_SEASONALITY_BY_WEEKDAY = (0.92, 0.95, 0.97, 1.00, 1.10, 1.15, 1.05)
_HOLIDAY_MULTIPLIER = {11: 1.35, 12: 1.55}
_COUNTRY_BY_CHANNEL = {"amazon": "US", "ebay": "DE", "woocommerce": "GB"}


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _order_id(channel: str, day: date, seq: int) -> str:
    return f"ord_{channel}_{day:%Y%m%d}_{seq:05d}"


def _order_line_id(order_id: str, line_no: int) -> str:
    return f"{order_id}-{line_no:02d}"


def _channel_order_id(channel: str, day: date, seq: int) -> str:
    # Ordinal day e.g. 2026-10-27 -> 739,916 (days since 0001-01-01)
    # Channel order ID pattern:
    #   Amazon : 113-0739916-xxxxxxx
    #   Ebay: 916-xxxxx-0739 (739916 % 1000 -> 916
    #                         739916 // 1000 -> 739)
    #   WooCommerce: 739916xxxx
    ordinal_day = day.toordinal()

    if channel == "amazon":
        return f"113-{ordinal_day:07d}-{seq:07d}"
    if channel == "ebay":
        return f"{ordinal_day % 1000:03d}-{seq:05d}-{ordinal_day // 1000:04d}"

    return f"{ordinal_day}{seq:04d}"


def _popularity_weight(cfg: Config, listing: Listing) -> float:
    # Deterministic fake popularity per product (superstars, mid-tier, dead products)
    rng = random.Random(f"{cfg.seed}:popularity:{listing.listing_id}")
    return max(rng.random(), 1e-9) ** cfg.popularity_alpha


def _daily_order_count(cfg: Config, day_rng: random.Random, day: date) -> int:
    low, high = cfg.per_day_orders_range
    base = day_rng.randint(low, high)
    multiplier = _SEASONALITY_BY_WEEKDAY[day.weekday()] * _HOLIDAY_MULTIPLIER.get(
        day.month, 1.0
    )
    return max(low, min(high, int(round(base * multiplier))))


def _split_by_channel(cfg: Config, total: int) -> dict[str, int]:
    # fixed order and normalize channel weight
    channels = sorted(cfg.store_channels)
    weight_sum = sum(cfg.channel_order_share[ch] for ch in channels)

    exact = {ch: total * cfg.channel_order_share[ch] / weight_sum for ch in channels}
    counts = {ch: int(exact[ch]) for ch in channels}
    leftover = total - sum(counts.values())

    # TODO: add short inline explanation of the algo
    ranked = sorted(channels, key=lambda ch: (-(exact[ch] - counts[ch]), ch))

    for ch in ranked[:leftover]:
        counts[ch] += 1

    return counts


# TODO: Deteministic sampling w/out replacement
# TODO: Timestamp and buyer metadata
# TODO: Day orders generator
# TODO: Generate whole date range orders
