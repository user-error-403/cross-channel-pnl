from datetime import date, time
from decimal import Decimal

import pytest

from script.synth.modules.config import Config
from script.synth.modules.reference import SERVICE_FEE_CONFIG
from script.synth.modules.service_fees import generate_service_fees

WINDOW_START = date(2025, 3, 1)
WINDOW_END = date(2025, 5, 31)

_SERVICE_FEE_KEYS = {
    "service_fee_id",
    "channel",
    "fee_type",
    "source_fee_type",
    "amount",
    "currency",
    "charged_at",
    "updated_at",
}


@pytest.fixture(scope="module")
def built() -> tuple[Config, list[dict]]:
    cfg = Config(start_date=WINDOW_START, end_date=WINDOW_END)

    return cfg, generate_service_fees(cfg)


def test_service_fee_config_targets_store_channels():
    cfg = Config()

    # Fail if a fee schedule points at a channel the store does not run
    assert set(SERVICE_FEE_CONFIG) <= set(cfg.store_channels)

    for rules in SERVICE_FEE_CONFIG.values():
        assert rules
        for rule in rules.values():
            assert rule["source_fee_type"]
            low, high = (Decimal(value) for value in rule["amount_range"])
            assert Decimal(0) < low <= high
            assert 1 <= rule["charge_day"] <= 28


def test_same_inputs_same_service_fees(built):
    cfg, fees = built

    # If not equal then a service fee stream leaks in process
    assert generate_service_fees(cfg) == fees


def test_one_row_per_month_and_fee_type(built):
    _, fees = built
    months = {(2025, 3), (2025, 4), (2025, 5)}
    expected = {
        f"svc_{channel}_{fee_type}_{year:04d}_{month:02d}"
        for channel, rules in SERVICE_FEE_CONFIG.items()
        for fee_type in rules
        for year, month in months
    }

    # Fail if a month is missing, repeated, or charged twice for one fee type
    assert {row["service_fee_id"] for row in fees} == expected
    assert len(fees) == len(expected)


def test_service_fee_rows_match_config(built):
    cfg, fees = built

    assert fees

    for row in fees:
        rule = SERVICE_FEE_CONFIG[row["channel"]][row["fee_type"]]
        low, high = (Decimal(value) for value in rule["amount_range"])

        assert set(row) == _SERVICE_FEE_KEYS
        assert row["source_fee_type"] == rule["source_fee_type"]
        # Fail if an amount escapes the configured range or loses its cents
        assert low <= row["amount"] <= high
        assert row["amount"] == row["amount"].quantize(Decimal("0.01"))
        assert row["currency"] == cfg.channel_currency[row["channel"]]
        assert row["currency"] in cfg.fx_rates
        assert row["charged_at"] == row["updated_at"]
        assert row["charged_at"].time() == time.min
        assert cfg.start_date <= row["charged_at"].date() <= cfg.end_date


def test_charges_outside_the_window_are_skipped():
    # Feb 8-20 contains neither the 1st nor the 7th
    assert (
        generate_service_fees(
            Config(start_date=date(2025, 2, 8), end_date=date(2025, 2, 20))
        )
        == []
    )

    # A partial January start drops January without shifting February
    partial = generate_service_fees(
        Config(start_date=date(2025, 1, 15), end_date=date(2025, 3, 31))
    )

    assert [row["service_fee_id"] for row in partial] == [
        "svc_amazon_storage_2025_02",
        "svc_amazon_subscription_2025_02",
        "svc_amazon_storage_2025_03",
        "svc_amazon_subscription_2025_03",
    ]


def test_one_month_does_not_depend_on_other_months(built):
    _, fees = built
    april = generate_service_fees(
        Config(start_date=date(2025, 4, 1), end_date=date(2025, 4, 30))
    )
    expected = [row for row in fees if row["service_fee_id"].endswith("_2025_04")]

    # Fail if a neighbouring month shifts April's charge
    assert april == expected
