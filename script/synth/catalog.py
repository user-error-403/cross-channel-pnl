import random
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from .config import Config
from .reference import BRAND_NAMES, CATEGORIES_LIST


class Brand(BaseModel):
    id: str
    name: str


class Category(BaseModel):
    id: str
    name: str


class Product(BaseModel):
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
    Build the synthetic catalog of priced products from `cfg` and the reference lists.

    - Referential Integrity: Every `brand_id` and `category_id` in `products`
      resolves inside the returned `brands` and `categories`.
    - Determinism: Products are keyed by `f"{cfg.seed}:product:{idx}"`, so
      changing `n_products` leaves existing products untouched.
    - Uniqueness: `Brand.id`, `Category.id`, and `Product.id` are unique within
      the returned `Catalog`.
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
        cost = Decimal(rand_entity.randint(300, 8000)) / 100

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
