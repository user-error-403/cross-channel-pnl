import random
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from faker import Faker

from .clock import SimClock
from .config import Config
from .listing import Listing
from .seeding import stage_faker

_MONEY = Decimal("0.01")
# Mon to Sun: values in days order
_SEASONALITY_BY_WEEKDAY = (0.92, 0.95, 0.97, 1.00, 1.10, 1.15, 1.05)
_HOLIDAY_MULTIPLIER = {11: 1.35, 12: 1.55}
_COUNTRY_BY_CHANNEL = {"amazon": "US", "ebay": "DE", "woocommerce": "GB"}


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _order_id(channel: str, day: date, sequence: int) -> str:
    return f"ord_{channel}_{day:%Y%m%d}_{sequence:05d}"


def _order_line_id(order_id: str, line_no: int) -> str:
    return f"{order_id}-{line_no:02d}"


# ------------------------------------------------------------
# SPLITING ORDERS HELPER FUNCTIONS
# ------------------------------------------------------------


def _popularity_weight(cfg: Config, listing: Listing) -> float:
    """Return the positive sampling weight of one listing, simulating product popularity."""
    rng = random.Random(f"{cfg.seed}:popularity:{listing.listing_id}")

    return max(rng.random(), 1e-9) ** cfg.popularity_alpha


def _daily_order_count(cfg: Config, day_rng: random.Random, day: date) -> int:
    """Draw the order count for one day, scaled by weekday and holiday seasonality."""
    low, high = cfg.per_day_orders_range
    base = day_rng.randint(low, high)
    multiplier = _SEASONALITY_BY_WEEKDAY[day.weekday()] * _HOLIDAY_MULTIPLIER.get(
        day.month, 1.0
    )

    return max(low, min(high, int(round(base * multiplier))))


def _split_by_channel(cfg: Config, total: int) -> dict[str, int]:
    """
    Divide a daily order total across channels by largest remainder.

    Shares are normalized by their own sum, so the configured values need not add
    up to 1.0. Remainder ties break on channel name ascending, which keeps a split
    identical across runs.

    Expectations:
    - `channel_order_share` values are non-negative; a negative share silently
      breaks the total, because the leftover loop then exhausts the ranking.

    Returns:
    - Values sum to `total`, and the key set equals `cfg.store_channels`.
    """
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


# Return example for '2026-10-27'
# Ordinal day equivalent: '739,916' (days since 0001-01-01)
# Channel order ID pattern:
#   Amazon : 113-0739916-xxxxxxx
#   Ebay: 916-xxxxx-0739 (739916 % 1000 -> 916
#                         739916 // 1000 -> 739)
#   WooCommerce: 739916xxxx
def _channel_order_id(channel: str, day: date, sequence: int) -> str:
    ordinal_day = day.toordinal()

    if channel == "amazon":
        return f"113-{ordinal_day:07d}-{sequence:07d}"
    if channel == "ebay":
        return f"{ordinal_day % 1000:03d}-{sequence:05d}-{ordinal_day // 1000:04d}"

    return f"{ordinal_day}{sequence:04d}"


def _placed_at(rng: random.Random, day: date) -> datetime:
    """Return a uniformly random UTC timestamp inside `day`."""
    seconds = rng.randint(0, 86_399)
    _time = time(seconds // 3600, seconds % 3600 // 60, seconds % 60)

    return datetime.combine(day, _time, tzinfo=timezone.utc)


def _buyer(faker: Faker, channel: str) -> dict:
    """Return the buyer identity and shipping fields for one order on `channel`."""

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
    cfg: Config,
    listings: list[Listing],
    day: date,
) -> list[dict]:
    """
    Generate one day of order headers and order lines for every channel.

    Workflow:
    - Initialize: seed a day-scoped RNG and Faker from `cfg.seed` and `day`.
    - Transform:
        - Draw the day's order total, then divide it across store channels
          by largest remainder.
        - Draw each order's timestamp, status, and line count, then pick its
          lines by popularity weight without replacement and price each line.
        - Rewrite the listing keys of orphan lines and swap the currency
          of defect lines at their configured rates.
    - Enrich: attach buyer identity and shipping fields from the day Faker.

    Expectations:
    - Given the same `cfg` and `listings`, a repeated `day` returns identical
      rows, because every draw is seeded from `cfg.seed` and `day`.
    - `item_count` counts units, and `gross_amount` is already net of
      `discount_amount`, so the two header amounts sum the same lines.
    - Every line carries the `order_id` of the header emitted alongside it.

    Returns:
    - A flat list interleaving one header per order with that order's lines,
      channels in name-ascending order.

    Failures:
    - Finding: A channel with no listings still emits headers with zero lines and
      zero amounts, so the day under-counts revenue without halting.
    """
    day_rng = random.Random(f"{cfg.seed}:orders:{day.isoformat()}")
    day_faker = stage_faker(cfg.seed, f"orders:{day.isoformat()}")

    total_orders = _daily_order_count(cfg, day_rng, day)
    ch_shares = _split_by_channel(cfg, total_orders)

    transactions: list[dict] = []
    for channel in sorted(ch_shares):
        item_pool = [itm for itm in listings if itm.channel == channel]
        weight = [_popularity_weight(cfg, itm) for itm in item_pool]

        for sequence in range(1, ch_shares[channel] + 1):
            # order-level randomization
            rng_order = random.Random(
                f"{cfg.seed}:order:{day.isoformat()}:{channel}:{sequence}"
            )

            order_id = _order_id(channel, day, sequence)
            placed_at = _placed_at(rng_order, day)
            n_lines = rng_order.randint(*cfg.items_per_order_range)

            orders = cfg.order_status_weights
            status = rng_order.choices(list(orders.keys()), list(orders.values()))[0]
            is_deleted = rng_order.random() < cfg.soft_delete_order_rate
            chosen_item = _sample_listings(rng_order, item_pool, weight, n_lines)

            order_lines: list[dict] = []
            for idx, item in enumerate(chosen_item, start=1):
                quantity = rng_order.randint(*cfg.units_per_line_range)
                unit_price = item.price

                if rng_order.random() < cfg.line_discount_rate:
                    low_pct, high_pct = cfg.line_discount_pct_range
                    pct = Decimal(str(rng_order.uniform(low_pct, high_pct)))
                    discount = _money(unit_price * quantity * pct)
                else:
                    discount = _money(Decimal("0"))

                gross = _money(unit_price * quantity - discount)

                is_orphan = rng_order.random() < cfg.orphan_line_rate
                is_currency_defect = rng_order.random() < cfg.currency_defect_rate

                line = {
                    "order_line_id": _order_line_id(order_id, idx),
                    "order_id": order_id,
                    "channel": channel,
                    "listing_id": item.listing_id,
                    "marketplace_id": item.marketplace_id,
                    "seller_sku": item.seller_sku,
                    "product_id": item.product_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "discount_amount": discount,
                    "gross_amount": gross,
                    "currency": item.currency,
                    "is_orphan": is_orphan,
                    "is_currency_defect": is_currency_defect,
                }

                # Inject data chaos
                if is_orphan:
                    line["listing_id"] = f"lst_orphan_{order_id[-5]}{idx:02d}"
                    line["marketplace_id"] = f"ORPHAN{order_id[-5]}{idx:02d}"
                    line["seller_sku"] = None
                    line["product_id"] = None

                if is_currency_defect:
                    # Relabel to another store channel's currency, excluding the current one
                    others = [ch for ch in sorted(cfg.store_channels) if ch != channel]
                    if others:
                        line["currency"] = cfg.channel_currency[others[0]]

                order_lines.append(line)

            buyer = _buyer(day_faker, channel)
            ch_order_id = _channel_order_id(channel, day, sequence)

            order_header = {
                "order_id": order_id,
                "channel": channel,
                "channel_order_id": ch_order_id,
                "placed_at": placed_at,
                "updated_at": placed_at,
                "currency": cfg.channel_currency[channel],
                "status": status,
                "is_deleted": is_deleted,
                "buyer_name": buyer["buyer_name"],
                "buyer_email": buyer["buyer_email"],
                "shipping_city": buyer["shipping_city"],
                "shipping_country": buyer["shipping_country"],
                "item_count": sum(line["quantity"] for line in order_lines),
                "discount_amount": _money(
                    sum(
                        (line["discount_amount"] for line in order_lines),
                        Decimal(0),
                    )
                ),
                "gross_amount": _money(
                    sum((line["gross_amount"] for line in order_lines), Decimal(0)),
                ),
            }

            transactions.append(order_header)
            transactions.extend(order_lines)

    return transactions


def generate_orders(
    cfg: Config,
    listings: list[Listing],
    clock: SimClock,
) -> list[dict]:
    """
    Return the rows for every day in the clock window, in date order.

    Delegates each day to `generate_orders_for_day`, so a day's rows depend only
    on `cfg.seed` and that date.
    """
    return [
        order
        for day in clock.iter_days()
        for order in generate_orders_for_day(cfg, listings, day)
    ]
