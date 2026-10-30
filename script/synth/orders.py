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
    """Daily orders total from the configured range, scaled by seasonality (Nov and Dec)."""
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


# ------------------------------------------------------------
# GENERATE ORDERS
# ------------------------------------------------------------


def generate_orders_for_day(
    cfg: Config, catalog: Catalog, listings: list[Listing], day: date
) -> list[dict]:
    day_rng = random.Random(f"{cfg.seed}:orders:{day.isoformat()}")
    day_faker = stage_faker(cfg.seed, f"orders:{day.isoformat()}")

    total_orders = _daily_order_count(cfg, day_rng, day)
    ch_shares = _split_by_channel(cfg, total_orders)

    rows: list[dict] = []
    for channel in sorted(ch_shares):
        item_pool = [itm for itm in listings if itm.channel == channel]
        weight = [_popularity_weight(cfg, itm) for itm in item_pool]

        for seq in range(1, ch_shares[channel] + 1):
            rng_order = random.Random(
                f"{cfg.seed}:order:{day.isoformat()}:{channel}:{seq}"
            )

            order_id = _order_id(channel, day, seq)
            placed_at = _placed_at(rng_order, day)
            n_lines = rng_order.randint(*cfg.items_per_order_range)

            orders = cfg.order_status_weights
            status = rng_order.choices(list(orders.keys()), list(orders.values()))
            is_deleted = rng_order.random() < cfg.soft_delete_order_rate
            chosen_item = _sample_listings(rng_order, item_pool, weight, n_lines)

            # TODO: Move to list dictionary, to enable calculation within rows dictionary key
            buyer = _buyer(day_faker, channel)
            order_line_id = _order_line_id(order_id, seq)
            ch_order_id = _channel_order_id(channel, day, seq)
            orphan_roll = cfg.orphan_line_rate
            currency_defect_roll = cfg.currency_defect_rate

            quantity = rng_order.randint(*cfg.units_per_line_range)
            unit_price = chosen_item[0].price

            order_line = {}
            if rng_order.random() < cfg.line_discount_rate:
                low_pct, high_pct = cfg.line_discount_pct_range
                pct = Decimal(str(rng_order.uniform(low_pct, high_pct)))
                discount = _money(unit_price * quantity * pct)
            else:
                discount = _money(Decimal("0"))

            gross = _money(unit_price * quantity - discount)

            rows.append(
                {
                    "order_id": order_id,
                    "channel": channel,
                    # "channel_order_id": #,
                    "placed_at": placed_at,
                    # "updated_at":, #,
                    # "currency":, #,
                    "status": status,
                    "is_deleted": is_deleted,
                    "buyer_name": buyer["buyer_name"],
                    "buyer_email": buyer["buyer_email"],
                    "shipping_city": buyer["shipping_city"],
                    "shipping_country": buyer["shipping_country"],
                    # "item_count":,
                    # "discount_amount":,
                    # "gross_amount":,
                }
            )

    return []
