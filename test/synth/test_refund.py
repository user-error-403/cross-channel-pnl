from datetime import date
from decimal import Decimal

import pytest

from script.synth.modules.catalog import Catalog, generate_catalog
from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config
from script.synth.modules.listing import Listing, generate_listings
from script.synth.modules.money_utils import money, window_end
from script.synth.modules.orders import generate_orders
from script.synth.modules.reference import (
    CATEGORIES_LIST,
    REFUND_CONFIG,
    REFUND_REASONS,
)
from script.synth.modules.refunds import generate_refunds
from script.synth.modules.seeding import stage_rng

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 1, 31)

_REFUND_KEYS = {
    "refund_id",
    "channel",
    "order_id",
    "order_line_id",
    "amount",
    "currency",
    "reason",
    "refunded_at",
    "updated_at",
    "is_partial",
    "is_orphan",
}


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config(start_date=WINDOW_START, end_date=WINDOW_END)


@pytest.fixture(scope="module")
def built(
    cfg,
) -> tuple[Config, Catalog, list[Listing], list[dict], list[dict]]:
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    orders = generate_orders(cfg, listings, SimClock.from_config(cfg))
    refunds = generate_refunds(cfg, catalog, orders)

    return cfg, catalog, listings, orders, refunds


def headers(orders: list[dict]) -> list[dict]:
    return [row for row in orders if "placed_at" in row]


def lines(orders: list[dict]) -> list[dict]:
    return [row for row in orders if "order_line_id" in row]


def test_refund_config_mirrors_categories():
    # Fail if a category has no refund rule, or a rule outlives its category
    assert set(REFUND_CONFIG) == set(CATEGORIES_LIST)

    for rule in REFUND_CONFIG.values():
        assert set(rule) == {"rate", "partial_share"}
        for value in rule.values():
            assert Decimal(0) < Decimal(value) < Decimal(1)


def test_same_inputs_same_refunds(built):
    cfg, catalog, _, orders, refunds = built

    # If not equal then a refund stream leaks in process
    assert generate_refunds(cfg, catalog, orders) == refunds


def test_one_line_refund_does_not_depend_on_other_lines(built):
    cfg, catalog, _, orders, refunds = built
    header_by_id = {row["order_id"]: row for row in headers(orders)}
    line_by_id = {row["order_line_id"]: row for row in lines(orders)}

    refund = next(item for item in refunds if not item["is_orphan"])
    line = line_by_id[refund["order_line_id"]]
    subset = [header_by_id[line["order_id"]], line]

    # If not equal then one line's refund shifts when other lines are present
    assert generate_refunds(cfg, catalog, subset) == [refund]


def test_refund_ids_are_unique_per_line(built):
    _, _, _, orders, refunds = built
    line_ids = {row["order_line_id"].replace("-", "_") for row in lines(orders)}
    refund_ids = [refund["refund_id"] for refund in refunds]

    assert len(set(refund_ids)) == len(refund_ids)

    for refund in refunds:
        # Fail if an orphan loses its source line and its key stops resolving
        assert refund["refund_id"].removeprefix("refund_") in line_ids

    line_refunds = [refund for refund in refunds if refund["order_line_id"] is not None]

    # Fail if one line refunds twice, which breaks the line grain
    assert len({refund["order_line_id"] for refund in line_refunds}) == len(
        line_refunds
    )


def test_refunds_reference_existing_orders_and_lines(built):
    cfg, catalog, _, orders, refunds = built
    header_by_id = {row["order_id"]: row for row in headers(orders)}
    line_by_id = {row["order_line_id"]: row for row in lines(orders)}
    products = {product.id: product for product in catalog.products}

    for refund in refunds:
        if refund["is_orphan"]:
            continue

        header = header_by_id[refund["order_id"]]
        line = line_by_id[refund["order_line_id"]]

        assert refund["channel"] == header["channel"]
        assert line["order_id"] == header["order_id"]
        assert line["product_id"] in products
        # Refunds carry no currency defect; the fee stream owns that one
        assert refund["currency"] == header["currency"]
        assert refund["currency"] in cfg.fx_rates
        # A refund lands after the sale, never on the order timestamp
        assert refund["refunded_at"] >= header["placed_at"]
        assert refund["updated_at"] == refund["refunded_at"]


def test_only_shipped_and_delivered_orders_refund(built):
    _, _, _, orders, refunds = built
    status_by_order = {row["order_id"]: row["status"] for row in headers(orders)}
    refunded_orders = {
        refund["order_id"] for refund in refunds if not refund["is_orphan"]
    }

    assert refunded_orders
    statuses = {status_by_order[order_id] for order_id in refunded_orders}

    # Fail if pending or cancelled orders emit refunds
    assert statuses <= {"shipped", "delivered"}


def test_refund_dates_follow_the_window(built):
    cfg, _, _, orders, refunds = built
    header_by_id = {row["order_id"]: row for row in headers(orders)}
    low, high = cfg.refund_window_days
    latest = window_end(cfg)

    for refund in refunds:
        if refund["is_orphan"]:
            continue

        header = header_by_id[refund["order_id"]]
        lag = (refund["refunded_at"] - header["placed_at"]).days

        assert cfg.start_date <= refund["refunded_at"].date() <= cfg.end_date
        assert refund["updated_at"] == refund["refunded_at"]
        assert lag <= high

        if refund["refunded_at"] != latest:
            # Fail if an unclamped refund ignores the configured window
            assert low <= lag <= high


def test_refund_amounts_stay_within_the_line(built):
    cfg, _, _, orders, refunds = built
    line_by_id = {row["order_line_id"]: row for row in lines(orders)}
    low_pct, high_pct = cfg.partial_refund_pct_range
    non_orphan = [refund for refund in refunds if not refund["is_orphan"]]
    partials = [refund for refund in non_orphan if refund["is_partial"]]
    fulls = [refund for refund in non_orphan if not refund["is_partial"]]

    # Fail if either amount basis never fires
    assert partials and fulls

    for refund in non_orphan:
        gross = line_by_id[refund["order_line_id"]]["gross_amount"]

        assert Decimal(0) < refund["amount"] <= gross
        assert refund["is_partial"] == (refund["amount"] < gross)

    for refund in partials:
        gross = line_by_id[refund["order_line_id"]]["gross_amount"]
        floor = money(gross * Decimal(str(low_pct)))
        ceiling = money(gross * Decimal(str(high_pct)))

        # Fail if the partial draw escapes the configured percentage range
        assert floor <= refund["amount"] <= ceiling

    for refund in fulls:
        assert refund["amount"] == line_by_id[refund["order_line_id"]]["gross_amount"]


def test_orphan_refund_rate_rewrites_the_order_keys():
    cfg = Config(
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        orphan_refund_rate=1.0,
    )
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    orders = generate_orders(cfg, listings, SimClock.from_config(cfg))
    refunds = generate_refunds(cfg, catalog, orders)
    order_ids = {row["order_id"] for row in headers(orders)}

    # Fail if the orphan draw does not rewrite the order keys
    assert refunds
    assert all(refund["is_orphan"] for refund in refunds)
    assert all(refund["order_line_id"] is None for refund in refunds)
    assert all(refund["order_id"] not in order_ids for refund in refunds)
    assert all(refund["amount"] > 0 for refund in refunds)


def test_refund_rows_have_a_fixed_shape(built):
    _, _, _, _, refunds = built

    for refund in refunds:
        assert set(refund) == _REFUND_KEYS
        assert refund["reason"] in REFUND_REASONS
        assert isinstance(refund["is_partial"], bool)
        assert isinstance(refund["is_orphan"], bool)
