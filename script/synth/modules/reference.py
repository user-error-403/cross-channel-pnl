CHANNEL_PROFILES: dict[str, dict] = {
    "amazon": {
        "sku_template": "{brand}-{item}-{code}",
        "sku_max_len": 40,
        "marketplace_id_kind": "asin",
        "title_style": "amazon",
        "title_max_len": 200,
    },
    "ebay": {
        "sku_template": "EB-{category}-{code}-{brand}-{item}-NEW-B12",
        "sku_max_len": 50,
        "marketplace_id_kind": "ebay_item_id",
        "title_style": "ebay",
        "title_max_len": 80,
    },
    "woocommerce": {
        "sku_template": "{category}-{item}-{code}",
        "sku_max_len": 50,
        "marketplace_id_kind": "woo_product_id",
        "title_style": "woocommerce",
        "title_max_len": 150,
    },
}

BRAND_NAMES: list[str] = [
    "Aurora",
    "Nordvik",
    "Lumen",
    "Vireo",
    "Cascade",
    "Kestrel",
    "Atlas",
    "Marlow",
    "Pinnacle",
    "Everline",
    "Novabright",
    "Halcyon",
    "Ridgeway",
    "Zephyr",
    "Copperleaf",
    "Brightloom",
    "Windmere",
    "Bastion",
    "Kodama",
    "Ferro",
    "Solstice",
    "Quillstone",
    "Amberfield",
    "Northgate",
]

CATEGORIES_LIST: dict[str, dict[str, list[str]]] = {
    "Home & Kitchen": {
        "items": [
            "Air Fryer",
            "Ceramic Mug Set",
            "Electric Kettle",
            "Storage Bin",
            "Chef Knife",
        ],
        "modifiers": ["Stainless Steel", "Non-Stick", "Stackable", "Insulated"],
    },
    "Beauty & Personal Care": {
        "items": [
            "Facial Cleanser",
            "Hair Dryer",
            "Beard Trimmer",
            "Body Lotion",
            "Makeup Brush Set",
        ],
        "modifiers": ["Hydrating", "Cordless", "Travel-Size", "Gentle"],
    },
    "Apparel & Accessories": {
        "items": [
            "Cotton T-Shirt",
            "Canvas Backpack",
            "Wool Beanie",
            "Rain Jacket",
            "Running Socks",
        ],
        "modifiers": ["Breathable", "Reversible", "Water-Resistant", "Unisex"],
    },
    "Health & Household": {
        "items": [
            "Air Purifier",
            "Humidifier",
            "First Aid Kit",
            "Electric Toothbrush",
            "Laundry Detergent",
        ],
        "modifiers": ["Hypoallergenic", "Concentrated", "Rechargeable", "Compact"],
    },
}

# scope: 'line' charges one fee per 'order line'; 'order' charges one fee per 'order'
# per_unit: multiplies flat and minimum by the line quantity
FEE_CONFIG: dict[str, dict[str, dict]] = {
    "amazon": {
        "referral": {
            "scope": "line",
            "per_unit": True,
            "percent_by_category": {
                "Home & Kitchen": "15",
                "Beauty & Personal Care": "15",
                "Apparel & Accessories": "17",
                "Health & Household": "15",
            },
            "fixed": "0",
            "minimum": "0.30",
        },
        "fulfillment": {
            "scope": "line",
            "per_unit": True,
            "percent": "0",
            "fixed": "3.68",
            "minimum": "0",
            "tiers": [
                {"max_base_cost": "10.00", "fixed": "3.06"},
                {"max_base_cost": "25.00", "fixed": "3.68"},
                {"max_base_cost": "50.00", "fixed": "5.64"},
                {"max_base_cost": None, "fixed": "6.92"},
            ],
        },
    },
    "ebay": {
        "final_value": {
            "scope": "line",
            "per_unit": False,
            "percent_by_category": {
                "Home & Kitchen": "13",
                "Beauty & Personal Care": "14",
                "Apparel & Accessories": "12",
                "Health & Household": "14",
            },
            "fixed": "0",
            "minimum": "0",
        },
        "final_value_fixed": {
            "scope": "order",
            "per_unit": False,
            "percent": "0",
            "fixed": "0.45",
            "minimum": "0",
        },
    },
    "woocommerce": {
        "gateway": {
            "scope": "order",
            "per_unit": False,
            "percent": "1.5",
            "fixed": "0.20",
            "minimum": "0",
        },
    },
}

SOURCE_FEE_TYPES: dict[str, dict[str, str]] = {
    "amazon": {
        "referral": "Commission",
        "fulfillment": "FBAPerUnitFulfillmentFee",
    },
    "ebay": {
        "final_value": "FINAL_VALUE_FEE",
        "final_value_fixed": "FINAL_VALUE_FEE_FIXED_PER_ORDER",
    },
    "woocommerce": {
        "gateway": "stripe_fee",
    },
}

# rate: share of eligible order lines that refund
# partial_share: share of refunds drawn as a partial amount
REFUND_CONFIG: dict[str, dict[str, str]] = {
    "Home & Kitchen": {"rate": "0.03", "partial_share": "0.35"},
    "Beauty & Personal Care": {"rate": "0.04", "partial_share": "0.40"},
    "Apparel & Accessories": {"rate": "0.07", "partial_share": "0.45"},
    "Health & Household": {"rate": "0.04", "partial_share": "0.35"},
}

REFUND_REASONS: list[str] = [
    "damaged",
    "wrong_item",
    "not_as_described",
    "changed_mind",
    "arrived_late",
    "defective",
]

# amount_range: inclusive monthly charge in local currency, as decimal strings
# charge_day: day of month the fee posts, always <= 28
SERVICE_FEE_CONFIG: dict[str, dict[str, dict]] = {
    "amazon": {
        "storage": {
            "source_fee_type": "StorageFee",
            "amount_range": ("18.00", "65.00"),
            "charge_day": 7,
        },
        "subscription": {
            "source_fee_type": "Subscription",
            "amount_range": ("39.99", "39.99"),
            "charge_day": 1,
        },
    },
}
