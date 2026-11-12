from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class Config(BaseModel):
    """
    The run settings shared by every synthetic-data generator.

    - Date Window: `start_date` and `end_date` are inclusive, so `days`
      is the difference plus one.
    - Key Coupling: `store_channels` keys the four channel maps and
      `reference.CHANNEL_PROFILES`.
    - FX Coverage: every `channel_currency` value needs an `fx_rates` key.
    - Share Weights: both weight maps divide by their own sum. Every status key
      becomes a status value in the orders.
    - Range Bounds: integer tuples include both ends. Float ranges stop short.
    - Defect Injection:
        - Listing: `sku_null_rate` emits no SKU. The separator, prefix, casing,
          and typo rates then hit that kept SKU in field order. If `drift_titlecase_rate`
          sits at or below `drift_lowercase_rate`, the title branch never runs.
        - Order: `orphan_line_rate` breaks the listing keys, `currency_defect_rate`
          relabels the line, and `soft_delete_order_rate` flags the header.
        - Fee: `fee_currency_defect_rate` relabels the fee to another channel's currency.
        - Refund: `orphan_refund_rate` breaks the order and line keys.
    - Rate Coupling: the casing rates share one draw, so keep
      `drift_titlecase_rate` above `drift_lowercase_rate`.
    - Window Clamping: fee and refund lags count from `placed_at`, and the
      generators truncate both at `end_date`.
    """

    seed: int = 42
    n_products: int = 33
    n_brands: int = 5

    # Date Window: 18 months range
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2026, 7, 1)

    # Key Coupling
    store_channels: list[str] = Field(
        default_factory=lambda: ["amazon", "ebay", "woocommerce"]
    )

    # FX Coverage
    default_currency: str = "USD"
    channel_currency: dict[str, str] = {
        "amazon": "USD",
        "ebay": "EUR",
        "woocommerce": "GBP",
    }

    # USD per 1 unit of foreign currency
    fx_rates: dict[str, float] = Field(
        default_factory=lambda: {"USD": 1.0, "EUR": 1.12, "GBP": 1.32}
    )

    # Multiplier on top of FX-converted price
    channel_price_multiplier: dict[str, float] = Field(
        default_factory=lambda: {"amazon": 1.00, "ebay": 0.97, "woocommerce": 0.95}
    )

    # Share Weights
    channel_order_share: dict[str, float] = Field(
        default_factory=lambda: {"amazon": 0.55, "ebay": 0.25, "woocommerce": 0.20}
    )
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

    # Range Bounds: Order Stream
    per_day_orders_range: tuple[int, int] = (2, 6)
    items_per_order_range: tuple[int, int] = (1, 2)
    units_per_line_range: tuple[int, int] = (1, 1)
    line_discount_pct_range: tuple[float, float] = (0.05, 0.15)

    # Range Bounds: Refund stream
    # Share of line gross that a partial refund returns
    partial_refund_pct_range: tuple[float, float] = (0.20, 0.80)
    refund_window_days: tuple[int, int] = (1, 30)

    # Range Bounds: Ad stream
    advertised_listing_share: float = 0.35
    ad_impressions_range: tuple[int, int] = (20, 600)
    ad_ctr_range: tuple[float, float] = (0.002, 0.02)
    ad_cpc_cents_range: tuple[int, int] = (30, 120)

    # Defect Injection: Listing
    sku_null_rate: float = 0.05
    separator_swap_rate: float = 0.15
    drift_channel_prefix_rate: float = 0.10
    drift_lowercase_rate: float = 0.20
    drift_titlecase_rate: float = 0.30
    drift_typo_rate: float = 0.05

    # Defect Injection: Order
    orphan_line_rate: float = 0.01
    soft_delete_order_rate: float = 0.005

    # Defect Injection: Fee
    currency_defect_rate: float = 0.01
    fee_currency_defect_rate: float = 0.01

    # Defect Injection: Refund
    orphan_refund_rate: float = 0.02

    # Window Clamping
    # Inclusive days between the order and the fee posting e.g. FBA ships
    channel_fee_lag_days: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "amazon": (1, 3),
            "ebay": (0, 1),
            "woocommerce": (0, 0),
        }
    )

    output_dir: Path = Path("data")

    # Inclusive day count and read only attribute
    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def n_days(self) -> int:
        return self.days
