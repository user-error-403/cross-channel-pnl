from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class Config(BaseModel):
    """
    Declare the run settings shared by every synthetic-data generator.

    - FX Direction: `fx_rates` holds USD per one unit of foreign currency, so a
      USD base price divides by the rate.
    - Date Window: `start_date` and `end_date` are both inclusive, so the span
      is the difference plus one.
    - Threshold Coupling: `drift_lowercase_rate` and `drift_titlecase_rate` are
      cumulative cut-offs on one draw, not independent probabilities.
    - Key Coupling: Every `store_channels` entry is keyed in `channel_currency`
      and `channel_price_multiplier`.
    """

    # TODO: Update docstring to inlcude orders configs

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

    # Order stream
    channel_order_share: dict[str, float] = Field(
        default_factory=lambda: {"amazon": 0.55, "ebay": 0.25, "woocommerce": 0.20}
    )
    items_per_order_range: tuple[int, int] = (1, 4)
    units_per_line_range: tuple[int, int] = (1, 3)
    order_status_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "pending": 0.05,
            "shipped": 0.15,
            "delivered": 0.75,
            "cancelled": 0.05,
        }
    )
    popularity_alpha: float = 2.5
    line_discount_rate: float = 0.20
    line_discount_pct_range: tuple[float, float] = (0.05, 0.15)
    orphan_line_rate: float = 0.01
    soft_delete_order_rate: float = 0.005
    currency_defect_rate: float = 0.01

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
