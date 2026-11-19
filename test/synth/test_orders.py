from collections import Counter
from datetime import date, timedelta
from itertools import groupby

import pytest

from script.synth.modules.catalog import generate_catalog
from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config
from script.synth.modules.listing import Listing, generate_listings
from script.synth.modules.orders import generate_orders, generate_orders_for_day
from script.synth.modules.seeding import stage_rng

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 1, 31)
SAMPLE_DAY = date(2025, 1, 15)


@pytest.fixture(scope="module")
def built() -> tuple[Config, list[Listing], list[dict]]:
    cfg = Config(
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        orphan_line_rate=1.0,
        soft_delete_order_rate=0.5,
    )
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    rows = generate_orders(cfg, listings, SimClock.from_config(cfg))

    return cfg, listings, rows


def headers(rows: list[dict]) -> list[dict]:
    return [r for r in rows if "channel_order_id" in r]


def lines(rows: list[dict]) -> list[dict]:
    return [r for r in rows if "order_line_id" in r]


def grouped(rows: list[dict]) -> dict[str, list[dict]]:
    return {
        key: list(group)
        for key, group in groupby(lines(rows), key=lambda r: r["order_id"])
    }


def test_same_day_twice_identical(built):
    cfg, listings, _ = built

    # If not equal then leaking in RNGs setup
    assert generate_orders_for_day(
        cfg, listings, SAMPLE_DAY
    ) == generate_orders_for_day(cfg, listings, SAMPLE_DAY)


def test_day_alone_equals_day_in_run(built):
    cfg, listings, rows = built
    day_ids = {
        row["order_id"]
        for row in headers(rows)
        if row["placed_at"].date() == SAMPLE_DAY
    }
    expected = [r for r in rows if r["order_id"] in day_ids]

    # If not equal then something wrong with determinism setup
    assert generate_orders_for_day(cfg, listings, SAMPLE_DAY) == expected


def test_every_day_present_and_in_range(built):
    cfg, _, rows = built
    low, high = cfg.per_day_orders_range
    counts = Counter(r["placed_at"].date() for r in headers(rows))
    window = {cfg.start_date + timedelta(days=i) for i in range(cfg.days)}

    assert set(counts) == window
    # Should pass else clamping fails in _daily_order_count()
    assert all(low <= n <= high for n in counts.values())


def test_ids_unique(built):
    _, _, rows = built
    hs, ls = headers(rows), lines(rows)
    assert len({row["order_id"] for row in hs}) == len(hs)
    assert len({row["channel_order_id"] for row in hs}) == len(hs)
    assert len({row["order_line_id"] for row in ls}) == len(ls)


def test_lines_chaos_injection(built):
    _, listings, rows = built
    by_id = {lst.listing_id: lst for lst in listings}
    orphans = 0

    for row in lines(rows):
        if row["is_orphan"]:
            orphans += 1
            assert row["product_id"] is None
            assert row["listing_id"] not in by_id
        else:
            listing = by_id[row["listing_id"]]
            assert row["product_id"] == listing.product_id
            assert row["channel"] == listing.channel

    assert orphans > 0


def test_cancelled_orders_keep_their_lines(built):
    cfg, _, rows = built
    hs = headers(rows)
    by_order = grouped(rows)

    cancelled = [row for row in hs if row["status"] == "cancelled"]
    deleted = [row for row in hs if row["is_deleted"]]

    assert cancelled
    assert deleted

    for row in cancelled + deleted:
        # Fail if header's order lines were drop
        assert by_order[row["order_id"]]

    assert {row["status"] for row in hs} <= set(cfg.order_status_weights)


def test_30_days_generated_transactions():
    cfg = Config(start_date=date(2025, 1, 1), end_date=date(2025, 1, 30))
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    rows = generate_orders(cfg, listings, SimClock.from_config(cfg))

    # Fail if nothing returns, fewer than 30 days total -> some days generate lower than min
    assert len(headers(rows)) > 30 * cfg.per_day_orders_range[0]
