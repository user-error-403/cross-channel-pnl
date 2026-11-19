import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .config import Config
from .reference import BRAND_NAMES, CATEGORIES_LIST


@dataclass
class Brand:
    id: str
    name: str


@dataclass
class Category:
    id: str
    name: str


@dataclass
class Product:
    id: str
    name: str
    brand_id: str
    category_id: str
    base_cost: Decimal  # supplier unit cost
    base_price: Decimal  # MSRP before channel adjustments


@dataclass
class Catalog:
    brands: list[Brand]
    categories: list[Category]
    products: list[Product]


def _make_id(prefix: str, i: int) -> str:
    return f"{prefix}_{i:05d}"


def generate_catalog(cfg: Config, rng: random.Random) -> Catalog:
    """
    Build the brand, category, and product lists for one run.

    Workflow:
    - Initialize: sample up to `cfg.n_brands` names from `BRAND_NAMES`.
    - Hydrate: copy every `CATEGORIES_LIST` key into a `Category`.
    - Transform: derive each product from a per-product RNG seeded with
      `cfg.seed`and the product index, then append it.

    Expectations:
    - Raising `cfg.n_products` appends products and leaves every existing `Product` untouched.

    Failures:
    - Finding: A `cfg.n_brands` above the length of `BRAND_NAMES` silently yields
      fewer brands, because the sample is capped instead of raising.
    """
    brands = [
        Brand(id=_make_id("br", i), name=name)
        for i, name in enumerate(
            rng.sample(BRAND_NAMES, k=min(cfg.n_brands, len(BRAND_NAMES))), 1
        )
    ]

    categories = [
        Category(id=_make_id("categ", idx), name=name)
        for idx, name in enumerate(CATEGORIES_LIST.keys(), 1)
    ]

    products: list[Product] = []
    for idx in range(1, cfg.n_products + 1):
        # Per entity/product randomization (rng)
        rand_entity = random.Random(f"{cfg.seed}:product:{idx}")
        brand = rand_entity.choice(brands)
        category = rand_entity.choice(categories)

        preset = CATEGORIES_LIST[category.name]
        mod = rand_entity.choice(preset["modifiers"])
        item = rand_entity.choice(preset["items"])

        # Integer cents to stay exact: (300 - 8000)/100 -> 3.00 - 80.00 USD.
        cost = (Decimal(rand_entity.randint(300, 8000)) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Initial margin covers marketplace fees, ads, and refunds.
        # Retail price = 1.8x to 2.5x the supplier cost (80% - 150% markup).
        markup_pct = Decimal(rand_entity.randint(80, 150)) / 100
        price = (cost * (1 + markup_pct)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        if price <= cost:
            raise ValueError("Product priced below cost")

        products.append(
            Product(
                id=_make_id("prod", idx),
                name=f"{brand.name} {mod} {item} {idx:04d}",
                brand_id=brand.id,
                category_id=category.id,
                base_cost=cost,
                base_price=price,
            )
        )

    return Catalog(brands=brands, categories=categories, products=products)
