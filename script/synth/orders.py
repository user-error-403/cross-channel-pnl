import random
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from faker import Faker

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


# ------------------------------------------------------------
# DETERMINISTIC SPLITS
# ------------------------------------------------------------


def _popularity_weight(cfg: Config, listing: Listing) -> float:
    """Fake popularity per product (superstars, mid-tier, dead products)"""
    rng = random.Random(f"{cfg.seed}:popularity:{listing.listing_id}")
    return max(rng.random(), 1e-9) ** cfg.popularity_alpha


def _daily_order_count(cfg: Config, day_rng: random.Random, day: date) -> int:
    """Daily orders total from the configured range, scaled by seasonality."""
    low, high = cfg.per_day_orders_range
    base = day_rng.randint(low, high)
    multiplier = _SEASONALITY_BY_WEEKDAY[day.weekday()] * _HOLIDAY_MULTIPLIER.get(
        day.month, 1.0
    )
    return max(low, min(high, int(round(base * multiplier))))


def _split_by_channel(cfg: Config, total: int) -> dict[str, int]:
    """Split `total` orders across the configured channels by channel order share."""
    # Sorted for deterministic ties
    channels = sorted(cfg.store_channels)
    share_total = sum(cfg.channel_order_share[ch] for ch in channels)

    frac_count = {
        ch: total * cfg.channel_order_share[ch] / share_total for ch in channels
    }
    base_count = {ch: int(frac_count[ch]) for ch in channels}
    leftover = total - sum(base_count.values())

    # Rank by largest remainder while keeping text ascending
    #   remainder: amazon 0.5 woocommerc 0.1 ebay 0.4
    #   negated:   amazon -0.5 woocommerce -0.1 ebay -0.4
    #   ranked:    ['amazon', 'ebay', 'woocomerce']
    remainder = {ch: frac_count[ch] - base_count[ch] for ch in channels}
    ranked = sorted(channels, key=lambda ch: (-remainder[ch], ch))

    for ch in ranked[:leftover]:
        base_count[ch] += 1

    return base_count


def _sample_listings(
    rng: random.Random,
    listing_pool: list[Listing],
    popularity_weights: list[float],
    n_listings: int,
) -> list[Listing]:
    """Select up to `n_listings` distinct listings to show, weighted by popularity"""
    items = list(zip(listing_pool, popularity_weights))
    picked: list[Listing] = []

    for _ in range(min(n_listings, len(items))):
        # Extract 'items' index. Biased to larger weights
        # Pop/remove the chosen listing from the pool so it can't be picked again
        idx = rng.choices(range(len(items)), weights=[w for _, w in items])[0]
        listing, _ = items.pop(idx)
        picked.append(listing)

    return picked


# ------------------------------------------------------------
# TRANSACTION METADATA
# ------------------------------------------------------------


def _placed_at(rng: random.Random, day: date) -> datetime:
    seconds = rng.randint(0, 86_399)
    _time = time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
    return datetime.combine(day, _time, tzinfo=timezone.utc)


def _buyer(faker: Faker, channel: str) -> dict:
    return {
        "buyer_name": faker.name(),
        "buyer_email": faker.email(),
        "shipping_city": faker.city(),
        "shipping_country": _COUNTRY_BY_CHANNEL.get(channel, "US"),
    }
