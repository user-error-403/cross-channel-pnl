import random
from datetime import date, datetime, time, timezone
from decimal import Decimal

from .clock import SimClock
from .config import Config
from .listing import Listing
from .money_utils import money

_AD_CHANNEL = "amazon"


def _campaign_info(listing: Listing) -> tuple[str, str]:
    return f"cmp_{listing.listing_id[-5:]}", f"SP-AUTO-{listing.product_id}"


def _is_advertised(cfg: Config, listing: Listing) -> bool:
    rng = random.Random(f"{cfg.seed}:ads:{listing.listing_id}")

    return rng.random() < cfg.advertised_listing_share


# ------------------------------------------------------------
# AD NUMBER HELPERS
# ------------------------------------------------------------


def _ad_number(cfg: Config, listing: Listing, day: date) -> tuple[int, int, Decimal]:
    """
    Draw one listing's day of ad activity.

    - Draw order is fixed: impressions, then CTR, then CPC. CPC is drawn even on
      a zero-click day, so one quiet day cannot shift the next day's sequence.
    - `clicks` is capped at `impressions`, so a widened CTR range can never
      report more clicks than impressions.
    """
    rng = random.Random(f"{cfg.seed}:ads:{listing.listing_id}:{day.isoformat()}")

    impressions = rng.randint(*cfg.ad_impressions_range)
    ctr = rng.uniform(*cfg.ad_ctr_range)
    cpc_cents = rng.randint(*cfg.ad_cpc_cents_range)

    clicks = min(int(round(impressions * ctr)), impressions)
    spend = money(Decimal(cpc_cents) / 100 * clicks)

    return impressions, clicks, spend


def _ad_row(
    listing: Listing,
    day: date,
    impressions: int,
    clicks: int,
    spend: Decimal,
) -> dict:
    """Assemble one ad report row from its listing and drawn numbers."""
    campaign_id, campaign_name = _campaign_info(listing)

    return {
        "ad_id": f"ad_{listing.listing_id}_{day:%Y%m%d}",
        "channel": listing.channel,
        "listing_id": listing.listing_id,
        "marketplace_id": listing.marketplace_id,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "report_date": day,
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "currency": listing.currency,
        "updated_at": datetime.combine(day, time.max, tzinfo=timezone.utc),
    }


# ------------------------------------------------------------
# GENERATE AD SPENDS
# ------------------------------------------------------------


def generate_ad_spends(
    cfg: Config,
    listings: list[Listing],
    clock: SimClock,
) -> list[dict]:
    """
    Return one ad report row per advertised Amazon listing per day.

    Each listing decides once whether it advertises for the whole window, and
    each advertised day draws from a `random.Random` keyed by listing and date.

    Expectations:
    - `clicks` never exceeds `impressions`, and `spend` is `clicks` times a CPC
      inside `ad_cpc_cents_range`.
    - An advertised listing reports every day in the `clock` window, from
      `start` through `end`.

    Returns:
    - Rows come out ordered by listing, then date.
    - A zero-click day still emits a row, with `spend` of `0.00`.
    """
    ads: list[dict] = []
    for listing in listings:
        if listing.channel != _AD_CHANNEL:
            continue
        if not _is_advertised(cfg, listing):
            continue

        for day in clock.iter_days():
            impressions, clicks, spend = _ad_number(cfg, listing, day)
            ads.append(
                _ad_row(
                    listing=listing,
                    day=day,
                    impressions=impressions,
                    clicks=clicks,
                    spend=spend,
                )
            )

    return ads
