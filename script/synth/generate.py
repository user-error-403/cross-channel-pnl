import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .modules.ad_spends import generate_ad_spends
from .modules.catalog import generate_catalog
from .modules.clock import SimClock
from .modules.config import Config
from .modules.fees import generate_fees
from .modules.listing import generate_listings
from .modules.orders import generate_orders
from .modules.refunds import generate_refunds
from .modules.seeding import stage_rng
from .modules.service_fees import generate_service_fees

SCHEMA_VERSION = 1

TABLES = (
    "brands",
    "categories",
    "products",
    "listings",
    "order_headers",
    "order_lines",
    "fees",
    "refunds",
    "ad_spends",
    "service_fees",
)


# Encode data types json can't handle
#   `Decimal` to `str`:  6.00 -> "6.00"
#   `date` to `ISO format`: "2025-01-01" -> "2025-01-01T10:12:00+00:00"
def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def generate_synth(cfg: Config) -> dict[str, list[dict]]:
    catalog = generate_catalog(cfg, stage_rng(cfg.seed, "catalog"))
    listings = generate_listings(cfg, catalog)
    clock = SimClock.from_config(cfg)
    orders = generate_orders(cfg, listings, clock)

    return {
        "brands": [asdict(brand) for brand in catalog.brands],
        "categories": [asdict(category) for category in catalog.categories],
        "products": [asdict(product) for product in catalog.products],
        "listings": [asdict(listing) for listing in listings],
        "order_headers": [row for row in orders if "placed_at" in row],
        "order_lines": [row for row in orders if "order_line_id" in row],
        "fees": generate_fees(cfg, catalog, orders),
        "refunds": generate_refunds(cfg, catalog, orders),
        "ad_spends": generate_ad_spends(cfg, listings, clock),
        "service_fees": generate_service_fees(cfg),
    }


def write_tables(
    cfg: Config,
    tables: dict[str, list[dict]],
) -> dict[str, int]:
    """Write one JSONL file per table plus `metadata.json`, returning row counts."""
    missing = [name for name in TABLES if name not in tables]
    if missing:
        raise ValueError(f"missing tables: {', '.join(missing)}")

    target = Path(cfg.output_dir)
    target.mkdir(parents=True, exist_ok=True)

    row_counts: dict[str, int] = {}
    for name in TABLES:
        rows = tables[name]
        row_counts[name] = len(rows)

        # Create the file even if it's empty, instead missing path
        with (target / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                line = json.dumps(
                    row,
                    default=_json_default,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                handle.write(f"{line}\n")

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "seed": cfg.seed,
        "start_date": cfg.start_date.isoformat(),
        "end_date": cfg.end_date.isoformat(),
        "tables": row_counts,
    }
    metadata_path = target / "metadata.json"
    metadata_text = json.dumps(metadata, sort_keys=True, ensure_ascii=False, indent=2)
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")

    return row_counts


def main() -> int:
    cfg = Config()
    tables = generate_synth(cfg)
    row_counts = write_tables(cfg, tables)
    width = max(len(name) for name in TABLES)

    # Print log
    for name in TABLES:
        print(f"{name:<{width}} {row_counts[name]:>}")
    print(f"{'total':<{width}} {sum(row_counts.values()):>}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
