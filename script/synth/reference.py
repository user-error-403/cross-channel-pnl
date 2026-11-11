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
    "Electronics": {
        "items": [
            "Wireless Earbuds",
            "Bluetooth Speaker",
            "Power Bank",
            "USB-C Hub",
            "Smart Plug",
        ],
        "modifiers": ["Compact", "Rechargeable", "Noise-Cancelling", "Portable"],
    },
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
    "Sports & Outdoors": {
        "items": [
            "Yoga Mat",
            "Resistance Bands",
            "Camping Lantern",
            "Hiking Backpack",
            "Water Bottle",
        ],
        "modifiers": ["Non-Slip", "Waterproof", "Lightweight", "Foldable"],
    },
    "Pet Supplies": {
        "items": [
            "Dog Harness",
            "Cat Scratching Post",
            "Slow Feeder Bowl",
            "Pet Carrier",
            "Grooming Kit",
        ],
        "modifiers": ["Adjustable", "Durable", "Washable", "Reflective"],
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
    "Toys & Games": {
        "items": [
            "Building Blocks Set",
            "Wooden Puzzle",
            "RC Car",
            "Board Game",
            "STEM Kit",
        ],
        "modifiers": ["Educational", "Colorful", "Interactive"],
    },
    "Office Products": {
        "items": [
            "Desk Organizer",
            "Wireless Mouse",
            "Monitor Stand",
            "Label Maker",
            "Notebook Set",
        ],
        "modifiers": ["Ergonomic", "Recycled", "Adjustable", "Heavy-Duty"],
    },
    "Tools & Home Improvement": {
        "items": [
            "Cordless Drill",
            "Screwdriver Set",
            "Tape Measure",
            "Tool Bag",
            "Wrench Set",
        ],
        "modifiers": ["Heavy-Duty", "Precision", "Cordless", "Compact"],
    },
    "Baby": {
        "items": [
            "Baby Monitor",
            "Stroller Organizer",
            "Silicone Bib",
            "Bottle Warmer",
            "Diaper Bag",
        ],
        "modifiers": ["BPA-Free", "Portable", "Soft-Touch", "Adjustable"],
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
    "Automotive": {
        "items": [
            "Phone Mount",
            "Tire Pressure Gauge",
            "Car Vacuum",
            "Dash Cam",
            "Seat Organizer",
        ],
        "modifiers": ["Universal", "Heavy-Duty", "Quick-Install", "Waterproof"],
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
                "Electronics": "8",
                "Home & Kitchen": "15",
                "Sports & Outdoors": "15",
                "Pet Supplies": "15",
                "Beauty & Personal Care": "15",
                "Toys & Games": "15",
                "Office Products": "15",
                "Tools & Home Improvement": "15",
                "Baby": "15",
                "Apparel & Accessories": "17",
                "Health & Household": "15",
                "Automotive": "12",
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
                "Electronics": "7",
                "Home & Kitchen": "13",
                "Sports & Outdoors": "14",
                "Pet Supplies": "14",
                "Beauty & Personal Care": "14",
                "Toys & Games": "14",
                "Office Products": "14",
                "Tools & Home Improvement": "14",
                "Baby": "14",
                "Apparel & Accessories": "12",
                "Health & Household": "14",
                "Automotive": "14",
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
