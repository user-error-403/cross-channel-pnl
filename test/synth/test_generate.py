import json
import re
from datetime import date, datetime

import pytest

from script.synth.generate import (
    SCHEMA_VERSION,
    TABLES,
    generate_synth,
    write_tables,
)
from script.synth.modules.catalog import generate_catalog
from script.synth.modules.clock import SimClock
from script.synth.modules.config import Config
from script.synth.modules.listing import generate_listings
from script.synth.modules.orders import generate_orders
from script.synth.modules.seeding import stage_rng

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2025, 1, 31)

_MONEY_FIELDS = {
    "products": ("base_cost", "base_price"),
    "listings": ("price",),
    "order_headers": ("discount_amount", "gross_amount"),
    "order_lines": ("unit_price", "discount_amount", "gross_amount"),
    "fees": ("amount",),
    "refunds": ("amount",),
    "ad_spends": ("spend",),
    "service_fees": ("amount",),
}
_DATETIME_FIELDS = {
    "order_headers": ("placed_at", "updated_at"),
    "fees": ("charged_at", "updated_at"),
    "refunds": ("refunded_at", "updated_at"),
    "ad_spends": ("updated_at",),
    "service_fees": ("charged_at", "updated_at"),
}
_DATE_FIELDS = {"ad_spends": ("report_date",)}

_MONEY_TEXT = re.compile(r"^\d+\.\d{2}$")


@pytest.fixture(scope="module")
def built() -> tuple[Config, dict[str, list[dict]]]:
    cfg = Config(start_date=WINDOW_START, end_date=WINDOW_END)

    return cfg, generate_synth(cfg)


def read_jsonl(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_generate_synth_returns_every_table(built):
    cfg, tables = built

    # Fail if a table is missing, reordered, or silently empty
    assert tuple(tables) == TABLES
    for name in TABLES:
        assert tables[name], f"{name} has no rows"

    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    orders = generate_orders(cfg, listings, SimClock.from_config(cfg))

    # Fail if the split drops or duplicates an order row
    assert len(tables["order_headers"]) + len(tables["order_lines"]) == len(orders)


def test_same_config_same_tables(built):
    cfg, tables = built

    # Fail if a generator leaks in-process state or dict order
    assert generate_synth(cfg) == tables


def test_write_tables_writes_jsonl_and_metadata(built, tmp_path):
    cfg, tables = built
    cfg = cfg.model_copy(update={"output_dir": tmp_path})
    counts = write_tables(cfg, tables)
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))

    # Fail if the counts drift between the return value and the metadata
    assert counts == metadata["tables"]
    assert counts == {name: len(tables[name]) for name in TABLES}
    assert set(metadata) == {
        "schema_version",
        "seed",
        "start_date",
        "end_date",
        "tables",
    }
    assert metadata["schema_version"] == SCHEMA_VERSION
    assert metadata["seed"] == cfg.seed
    assert metadata["start_date"] == cfg.start_date.isoformat()
    assert metadata["end_date"] == cfg.end_date.isoformat()

    for name in TABLES:
        rows = read_jsonl(tmp_path / f"{name}.jsonl")
        assert len(rows) == counts[name]

        for row in rows:
            for field in _MONEY_FIELDS.get(name, ()):
                value = row[field]
                # Fail if money crosses as a float or loses its cents
                assert isinstance(value, str)
                assert _MONEY_TEXT.match(value), (name, field, value)

            for field in _DATETIME_FIELDS.get(name, ()):
                parsed = datetime.fromisoformat(row[field])
                assert parsed.tzinfo is not None

            for field in _DATE_FIELDS.get(name, ()):
                assert date.fromisoformat(row[field])
