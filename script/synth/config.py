from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class Config(BaseModel):
    """
    Define the configuration contract for every synthetic-data generator.

    `default_currency` and `per_day_orders_range` are declared but never read.

    Contract:
    - Transformation: `fx_rates` holds the USD value of one unit of each foreign currency; the price path divides the USD base by that rate, then applies `channel_price_multiplier`.
    - Referential Integrity: Every `store_channels` entry must key into `channel_currency` and `channel_price_multiplier`, and every `channel_currency` value must key into `fx_rates`.
      Construction validates none of these references.
    - Data Constraint: Drift rates are probabilities in [0, 1].
      `drift_titlecase_rate` is an absolute threshold applied after
      `drift_lowercase_rate`, so its marginal share is the difference.
      Construction validates neither bound.
    - Temporal Alignment: `start_date` and `end_date` bound an inclusive window;`days` counts both ends.

    Failures:
    - Crash: `KeyError` during listing generation when a `store_channels` entry is missing from `channel_currency` or `channel_price_multiplier`.
    """

    seed: int = 42

    # 18 months range
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2026, 7, 1)

    store_channels: list[str] = Field(
        default_factory=lambda: ["amazon", "ebay", "woocommerce"]
    )

    n_products: int = 315
    n_brands: int = 23
    per_day_orders_range: tuple[int, int] = (50, 250)

    # USD per 1 unit of foreign currency
    default_currency: str = "USD"
    fx_rates: dict[str, float] = Field(
        default_factory=lambda: {"USD": 1.0, "EUR": 1.12, "GBP": 1.32}
    )

    channel_currency: dict[str, str] = {
        "amazon": "USD",
        "ebay": "EUR",
        "woocommerce": "GBP",
    }

    # Multiplier on top of FX-converted price
    channel_price_multiplier: dict[str, float] = Field(
        default_factory=lambda: {"amazon": 1.00, "ebay": 0.97, "woocommerce": 0.95}
    )

    sku_null_rate: float = 0.05
    separator_swap_rate: float = 0.15
    drift_channel_prefix_rate: float = 0.10
    drift_lowercase_rate: float = 0.20
    drift_titlecase_rate: float = 0.30
    drift_typo_rate: float = 0.05

    output_dir: Path = Path("data")

    # Inclusive day count and read only attribute
    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def n_days(self) -> int:
        return self.days
