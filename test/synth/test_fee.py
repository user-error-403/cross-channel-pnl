from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest

from script.synth.modules.catalog import generate_catalog
from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config
from script.synth.modules.listing import Listing, generate_listings
from script.synth.modules.fees import generate_fees
from script.synth.modules.orders import generate_orders
from script.synth.modules.reference import FEE_CONFIG, SOURCE_FEE_TYPES
from script.synth.modules.seeding import stage_rng

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 1, 31)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return Config(start_date=WINDOW_START, end_date=WINDOW_END)


@pytest.fixture(scope="module")
def built(cfg) -> tuple[Config, list[Listing], list[dict], list[dict]]:
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    orders = generate_orders(cfg, listings, SimClock.from_config(cfg))
    fees = generate_fees(cfg, catalog, orders)

    return cfg, listings, orders, fees


def headers(orders: list[dict]) -> list[dict]:
    return [row for row in orders if "placed_at" in row]


def lines(orders: list[dict]) -> list[dict]:
    return [row for row in orders if "order_line_id" in row]


def expected_amount(
    rule: dict,
    gross: Decimal,
    units: int,
    category: str | None,
    base_cost: Decimal | None,
) -> Decimal:
    if "percent_by_category" in rule:
        rate = Decimal(rule["percent_by_category"][category])
    else:
        rate = Decimal(rule["percent"])

    fixed = Decimal(rule["fixed"])
    for tier in rule.get("tiers", ()):
        limit = tier["max_base_cost"]
        if limit is None or (base_cost is not None and base_cost <= Decimal(limit)):
            fixed = Decimal(tier["fixed"])
            break

    multiplier = units if rule["per_unit"] else 1
    amount = gross * rate / 100
    amount += fixed * multiplier
    amount = max(amount, Decimal(rule["minimum"]) * multiplier)

    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_fee_schedules_mirror_channels(cfg):
    # Fail if a channel exists without a fee schedule, or the other way around
    assert set(FEE_CONFIG) == set(cfg.store_channels)


def test_source_fee_types_mirror_schedule():
    # Fail if a fee type has no payload label, or a label outlives its rule
    assert set(SOURCE_FEE_TYPES) == set(FEE_CONFIG)

    for channel, rules in FEE_CONFIG.items():
        assert set(SOURCE_FEE_TYPES[channel]) == set(rules), channel
        assert all(SOURCE_FEE_TYPES[channel].values()), channel


def test_fee_tiers_are_ordered_and_total():
    for _, rules in FEE_CONFIG.items():
        for _, rule in rules.items():
            tiers = rule.get("tiers")
            if tiers is None:
                continue

            # Fail if an order rule gains tiers, which has no cost to resolve
            assert rule["scope"] == "line"

            limits = [tier["max_base_cost"] for tier in tiers]

            # Fail if the last tier is bounded, so some cost finds no tier
            assert limits[-1] is None
            assert limits[-2] is not None

            # Fail if tiers are out of order, which over-applies the first match
            bounds = [Decimal(limit) for limit in limits[:-1]]
            assert bounds == sorted(bounds)
            assert all(Decimal(tier["fixed"]) > 0 for tier in tiers)


def test_same_inputs_same_fees(built):
    cfg, _, orders, fees = built
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))

    # If not equal then a fee stream leaks in process
    assert generate_fees(cfg, catalog, orders) == fees


def test_one_order_fees_do_not_depend_on_other_orders(built):
    cfg, _, orders, fees = built
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    lines_by_order: dict[str, list[dict]] = {}
    for row in lines(orders):
        lines_by_order.setdefault(row["order_id"], []).append(row)

    header = next(
        row
        for row in headers(orders)
        if row["status"] != "cancelled"
        and any(fee["order_id"] == row["order_id"] for fee in fees)
    )
    subset = [header, *lines_by_order[header["order_id"]]]
    expected = [fee for fee in fees if fee["order_id"] == header["order_id"]]

    # If not equal then one order's rows shift when other orders are present
    assert generate_fees(cfg, catalog, subset) == expected


def test_fee_ids_unique(built):
    _, _, _, fees = built
    assert len({fee["fee_id"] for fee in fees}) == len(fees)


def test_fee_types_are_valid_for_channel(built):
    _, _, _, fees = built

    for fee in fees:
        assert fee["fee_type"] in FEE_CONFIG[fee["channel"]]
        assert (
            fee["source_fee_type"] == SOURCE_FEE_TYPES[fee["channel"]][fee["fee_type"]]
        )
        # Fail if the canonical layer leaks a payload label into `fee_type`
        assert fee["fee_type"] != fee["source_fee_type"]


def test_fees_reference_existing_orders_and_lines(built):
    cfg, _, orders, fees = built
    header_by_id = {row["order_id"]: row for row in headers(orders)}

    for fee in fees:
        header = header_by_id[fee["order_id"]]

        assert fee["channel"] == header["channel"]
        # Fees post after the sale, so they never reuse the order timestamps
        assert fee["charged_at"] >= header["placed_at"]
        assert fee["updated_at"] == fee["charged_at"]

        if fee["is_currency_defect"]:
            # Defect row is relabelled, never converted, so the amount stands
            assert fee["currency"] != header["currency"]
        else:
            assert fee["currency"] == header["currency"]

        assert fee["currency"] in cfg.fx_rates


def test_fee_postings_follow_lag_and_window(built):
    cfg, _, orders, fees = built
    header_by_id = {row["order_id"]: row for row in headers(orders)}
    latest = datetime.combine(cfg.end_date, time.max, tzinfo=timezone.utc)
    lags = set()

    for fee in fees:
        header = header_by_id[fee["order_id"]]
        low, high = cfg.channel_fee_lag_days[fee["channel"]]
        lag = (fee["charged_at"] - header["placed_at"]).days
        lags.add(lag)

        if header["placed_at"] + timedelta(days=high) <= latest:
            # Fail if a fee posts before the money moves, or later than FBA ships
            assert low <= lag <= high
        else:
            assert 0 <= lag <= high

        # Fail if a late posting escapes the run window
        assert cfg.start_date <= fee["charged_at"].date() <= cfg.end_date
        assert cfg.start_date <= fee["updated_at"].date() <= cfg.end_date


def test_cancelled_orders_charge_no_fees(built):
    _, _, orders, fees = built
    cancelled = {
        row["order_id"] for row in headers(orders) if row["status"] == "cancelled"
    }

    fee_order_ids = {fee["order_id"] for fee in fees}

    # Fail if a cancelled order still carries marketplace fees
    assert cancelled
    assert not any(order_id in fee_order_ids for order_id in cancelled)


def test_orphan_lines_charge_no_fees():
    cfg = Config(
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        orphan_line_rate=1.0,
    )
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    orders = generate_orders(cfg, listings, SimClock.from_config(cfg))
    fees = generate_fees(cfg, catalog, orders)

    # An orphan line has no catalog product, so only order-scoped fees survive
    assert lines(orders)
    assert all(row["is_orphan"] for row in lines(orders))
    assert fees
    assert all(fee["order_line_id"] is None for fee in fees)


def test_fee_amounts_match_schedule(built):
    _, _, orders, fees = built
    cfg = Config(start_date=WINDOW_START, end_date=WINDOW_END)
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    products = {prod.id: prod for prod in catalog.products}
    category_name = {cat.id: cat.name for cat in catalog.categories}
    header_by_id = {row["order_id"]: row for row in headers(orders)}
    line_by_id = {row["order_line_id"]: row for row in lines(orders)}

    assert fees

    for fee in fees:
        rule = FEE_CONFIG[fee["channel"]][fee["fee_type"]]

        if fee["order_line_id"] is None:
            gross = header_by_id[fee["order_id"]]["gross_amount"]
            expected = expected_amount(rule, gross, 1, None, None)
        else:
            line = line_by_id[fee["order_line_id"]]
            product = products[line["product_id"]]
            gross = line["gross_amount"]
            expected = expected_amount(
                rule,
                gross,
                line["quantity"],
                category_name[product.category_id],
                product.base_cost,
            )

        assert fee["amount"] == expected
        # Fail if a zero or negative amount
        assert all(fee["amount"] > 0 for fee in fees)


def test_fee_rows_cover_every_schedule_entry(built):
    _, _, _, fees = built
    seen = {(fee["channel"], fee["fee_type"]) for fee in fees}
    expected = {
        (channel, fee_type)
        for channel, rules in FEE_CONFIG.items()
        for fee_type in rules
    }

    # Fail if a schedule entry never fires, e.g. a scope typo
    assert seen == expected


def test_currency_defects_are_flagged_and_bounded(built):
    cfg, _, _, fees = built
    defects = [fee for fee in fees if fee["is_currency_defect"]]

    assert defects
    assert len(defects) < len(fees)
    # Fail if the defect knob is ignored or applied to a much larger share
    ceiling = int(cfg.fee_currency_defect_rate * len(fees) * 3) + 1
    assert len(defects) <= ceiling
