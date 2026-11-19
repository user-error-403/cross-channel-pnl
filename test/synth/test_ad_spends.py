from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest

from script.synth.modules.ad_spends import generate_ad_spends
from script.synth.modules.catalog import generate_catalog
from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config
from script.synth.modules.listing import Listing, generate_listings
from script.synth.modules.money_utils import money
from script.synth.modules.seeding import stage_rng

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 1, 31)

_AD_KEYS = {
    "ad_id",
    "channel",
    "listing_id",
    "marketplace_id",
    "campaign_id",
    "campaign_name",
    "report_date",
    "impressions",
    "clicks",
    "spend",
    "currency",
    "updated_at",
}


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config(
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        advertised_listing_share=1.0,
    )


@pytest.fixture(scope="module")
def built(cfg) -> tuple[Config, list[Listing], list[dict]]:
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    ads = generate_ad_spends(cfg, listings, SimClock.from_config(cfg))

    return cfg, listings, ads


def test_same_inputs_same_ad_rows(built):
    cfg, listings, ads = built

    # If not equal then an ad stream leaks in process
    assert generate_ad_spends(cfg, listings, SimClock.from_config(cfg)) == ads


def test_only_amazon_listings_advertise(built):
    _, listings, ads = built
    amazon_ids = {
        listing.listing_id for listing in listings if listing.channel == "amazon"
    }
    advertised = {row["listing_id"] for row in ads}

    assert ads
    assert all(row["channel"] == "amazon" for row in ads)

    # Fail if a non-amazon listing leaks into the ad stream
    assert advertised == amazon_ids


def test_ad_rows_are_daily_per_advertised_listing(built):
    cfg, listings, ads = built
    listing_by_id = {listing.listing_id: listing for listing in listings}
    days = list(SimClock.from_config(cfg).iter_days())
    ad_ids = [row["ad_id"] for row in ads]

    assert len(set(ad_ids)) == len(ad_ids)

    rows_by_listing: dict[str, list[dict]] = {}
    for row in ads:
        rows_by_listing.setdefault(row["listing_id"], []).append(row)

    for listing_id, rows in rows_by_listing.items():
        listing = listing_by_id[listing_id]

        # Fail if a listing skips a day, repeats one, or stops at a partial window
        assert [row["report_date"] for row in rows] == days
        assert {row["ad_id"] for row in rows} == {
            f"ad_{listing_id}_{day:%Y%m%d}" for day in days
        }

        # One campaign owns the listing, derived from the listing itself
        assert len({(row["campaign_id"], row["campaign_name"]) for row in rows}) == 1
        assert rows[0]["campaign_id"] == f"cmp_{listing_id[-5:]}"
        assert rows[0]["campaign_name"] == f"SP-AUTO-{listing.product_id}"


def test_ad_rows_follow_the_listing_and_the_window(built):
    cfg, listings, ads = built
    listing_by_id = {listing.listing_id: listing for listing in listings}

    for row in ads:
        listing = listing_by_id[row["listing_id"]]
        day = row["report_date"]

        assert set(row) == _AD_KEYS
        assert row["marketplace_id"] == listing.marketplace_id
        assert row["currency"] == listing.currency
        assert cfg.start_date <= day <= cfg.end_date
        # A report row closes its own day, never the window end
        assert row["updated_at"] == datetime.combine(day, time.max, tzinfo=timezone.utc)


def test_ad_numbers_reconcile(built):
    cfg, _, ads = built
    low_cents, high_cents = cfg.ad_cpc_cents_range
    low_impressions, high_impressions = cfg.ad_impressions_range

    for row in ads:
        assert low_impressions <= row["impressions"] <= high_impressions
        assert 0 <= row["clicks"] <= row["impressions"]

        if row["clicks"] == 0:
            assert row["spend"] == Decimal("0.00")
            continue

        # Spend is CPC x clicks, so each click costs a drawn number of cents
        cpc = row["spend"] / row["clicks"]
        assert Decimal(low_cents) / 100 <= cpc <= Decimal(high_cents) / 100
        assert row["spend"] == money(cpc * row["clicks"])


def test_zero_click_days_emit_zero_spend(built):
    _, listings, _ = built
    cfg = Config(
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        ad_ctr_range=(0.0, 0.0),
        advertised_listing_share=1.0,
    )

    ads = generate_ad_spends(cfg, listings, SimClock.from_config(cfg))

    assert ads
    assert all(row["clicks"] == 0 for row in ads)
    assert all(row["spend"] == Decimal("0.00") for row in ads)
