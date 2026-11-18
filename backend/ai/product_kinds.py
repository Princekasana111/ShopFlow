"""What a product *is*, for the purchase check's duplicate and alternative checks.

Two products of the same kind do the same job (two pairs of running shoes). Kinds in the same group
do a similar job (headphones and earbuds, a flask and a water bottle). Each kind also carries a
rule-of-thumb replacement interval, so buying new running shoes after a year is not flagged as a
duplicate, and whether owning several is normal (T-shirts, socks, chargers).

The kind is read from the product name (and the category as a fallback). With Claude available,
the LLM judges whether two products do the same job instead; these rules are the offline version
and cover every product in the demo catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    plural: str
    group: str
    lifespan_months: int | None  # rule of thumb for regular use; None = no typical replacement
    multiples_ok: bool = False  # owning several different ones is normal
    same_item_ok: bool = False  # buying the identical product again is normal (consumables, basics)


K = Kind
_KINDS = [
    K("headphones", "headphones", "headphones", "personal-audio", 36),
    K("earbuds", "earbuds", "earbuds", "personal-audio", 24),
    K("speaker", "Bluetooth speaker", "Bluetooth speakers", "speaker", 36),
    K("power-bank", "power bank", "power banks", "power-bank", 36),
    K("smartwatch", "smartwatch", "smartwatches", "smartwatch", 36),
    K("keyboard", "keyboard", "keyboards", "keyboard", 60),
    K("mouse", "mouse", "mice", "mouse", 36),
    K("webcam", "webcam", "webcams", "webcam", 48),
    K("monitor", "monitor", "monitors", "monitor", 72, multiples_ok=True, same_item_ok=True),
    K("charger", "charger", "chargers", "charger", 48, multiples_ok=True, same_item_ok=True),
    K("hiking-boots", "hiking boots", "hiking boots", "hiking-boots", 24),
    K("running-shoes", "running shoes", "running shoes", "running-shoes", 9),
    K("court-shoes", "court shoes", "court shoes", "court-shoes", 12),
    K("kids-shoes", "kids' shoes", "kids' shoes", "kids-shoes", 9),
    K("flip-flops", "flip-flops", "flip-flops", "open-footwear", 12),
    K("sandals", "sandals", "sandals", "open-footwear", 24),
    K("slippers", "slippers", "slippers", "slippers", 12),
    K("formal-shoes", "formal shoes", "formal shoes", "formal-shoes", 36),
    K("sneakers", "sneakers", "sneakers", "sneakers", 18, multiples_ok=True),
    K("sports-tee", "sports T-shirt", "sports T-shirts", "t-shirts", 18, multiples_ok=True, same_item_ok=True),
    K("tee", "T-shirt", "T-shirts", "t-shirts", 18, multiples_ok=True, same_item_ok=True),
    K("puffer-jacket", "warm jacket", "warm jackets", "warm-layers", 48),
    K("hoodie", "hoodie", "hoodies", "warm-layers", 36, multiples_ok=True),
    K("rain-jacket", "rain jacket", "rain jackets", "rain-jacket", 36),
    K("jeans", "jeans", "jeans", "jeans", 24, multiples_ok=True, same_item_ok=True),
    K("shirt", "shirt", "shirts", "shirts", 24, multiples_ok=True),
    K("kurta", "kurta", "kurtas", "ethnic-wear", 36, multiples_ok=True),
    K("socks", "socks", "socks", "socks", 12, multiples_ok=True, same_item_ok=True),
    K("leggings", "leggings", "leggings", "activewear", 18, multiples_ok=True, same_item_ok=True),
    K("flask", "insulated flask", "insulated flasks", "drinkware", 60),
    K("water-bottle", "water bottle", "water bottles", "drinkware", 48),
    K("frying-pan", "frying pan", "frying pans", "frying-pan", 24),
    K("kettle", "electric kettle", "electric kettles", "kettle", 48),
    K("air-fryer", "air fryer", "air fryers", "air-fryer", 60),
    K("cutting-board", "cutting board set", "cutting board sets", "cutting-board", 36),
    K("chef-knife", "chef's knife", "chef's knives", "knife", 120),
    K("curtains", "curtains", "curtains", "curtains", 84, multiples_ok=True, same_item_ok=True),
    K("bedsheet", "bedsheet set", "bedsheet sets", "bedding", 36, multiples_ok=True, same_item_ok=True),
    K("desk-lamp", "desk lamp", "desk lamps", "lamp", 72),
    K("book", "book", "books", "book", None, multiples_ok=True),
    K("yoga-mat", "yoga mat", "yoga mats", "exercise-mat", 24),
    K("dumbbells", "dumbbell set", "dumbbell sets", "weights", 240),
    K("resistance-bands", "resistance bands", "resistance bands", "resistance-bands", 12),
    K("cricket-bat", "cricket bat", "cricket bats", "cricket-bat", 24),
    K("tennis-ball-bat", "tennis-ball bat", "tennis-ball bats", "cricket-bat", 18),
    K("football", "football", "footballs", "football", 18),
    K("badminton-racket", "badminton racket", "badminton rackets", "racket", 36),
    K("skipping-rope", "skipping rope", "skipping ropes", "skipping-rope", 24),
    K("foam-roller", "foam roller", "foam rollers", "foam-roller", 48),
    K("cycling-helmet", "cycling helmet", "cycling helmets", "helmet", 60),
]
KINDS: dict[str, Kind] = {k.key: k for k in _KINDS}

# Order matters: the first match wins ("Kids Light-Up Sneakers" before "sneakers", "T-Shirt" before "shirt").
_RULES = [
    (r"headphone", "headphones"), (r"earbud|earphone", "earbuds"), (r"speaker", "speaker"),
    (r"power ?bank", "power-bank"), (r"smart ?watch|fitness tracker", "smartwatch"), (r"keyboard", "keyboard"),
    (r"\bmouse\b", "mouse"), (r"webcam", "webcam"), (r"monitor", "monitor"), (r"charger", "charger"),
    (r"hiking|\bboots?\b", "hiking-boots"), (r"running shoe|\brunners?\b|trail shoe", "running-shoes"),
    (r"badminton shoe|court shoe", "court-shoes"), (r"light-?up|kids'? (shoe|sneaker)", "kids-shoes"),
    (r"flip-?flop", "flip-flops"), (r"sandal", "sandals"), (r"slipper", "slippers"),
    (r"oxford|formal shoe|leather shoe", "formal-shoes"), (r"sneaker", "sneakers"),
    (r"sports t-?shirt|jersey", "sports-tee"), (r"\btee\b|t-?shirt", "tee"),
    (r"puffer|down jacket|winter jacket", "puffer-jacket"), (r"rain ?jacket|raincoat|poncho", "rain-jacket"),
    (r"\bjeans\b|denim", "jeans"), (r"kurta", "kurta"), (r"\bshirt\b", "shirt"), (r"hoodie|sweatshirt", "hoodie"),
    (r"\bsocks?\b", "socks"), (r"leggings|yoga pants", "leggings"),
    (r"flask|thermos", "flask"), (r"water bottle|\bbottle\b", "water-bottle"),
    (r"frying pan|skillet", "frying-pan"), (r"kettle", "kettle"), (r"air ?fryer", "air-fryer"),
    (r"cutting board|chopping board", "cutting-board"), (r"knife", "chef-knife"), (r"curtain", "curtains"),
    (r"bed ?sheet", "bedsheet"), (r"\blamp\b", "desk-lamp"),
    (r"yoga mat|exercise mat", "yoga-mat"), (r"dumbbell", "dumbbells"), (r"resistance band", "resistance-bands"),
    (r"tennis[- ]ball bat|kashmir willow", "tennis-ball-bat"), (r"cricket bat|english willow", "cricket-bat"),
    (r"football|soccer ball", "football"), (r"racket|racquet", "badminton-racket"),
    (r"skipping rope|jump rope", "skipping-rope"), (r"foam roller", "foam-roller"), (r"helmet", "cycling-helmet"),
]
_COMPILED = [(re.compile(p, re.I), key) for p, key in _RULES]
_CATEGORY_FALLBACK = {"books": "book"}

GROUP_LABELS = {
    "personal-audio": "Headphones & earbuds", "drinkware": "Bottles & flasks", "t-shirts": "T-shirts",
    "warm-layers": "Jackets & warm layers", "open-footwear": "Sandals & flip-flops", "cricket-bat": "Cricket bats",
}


def kind_of(name: str, category_slug: str | None = None) -> Kind:
    for pattern, key in _COMPILED:
        if pattern.search(name or ""):
            return KINDS[key]
    key = _CATEGORY_FALLBACK.get(category_slug or "")
    if key:
        return KINDS[key]
    other = f"other-{category_slug or 'misc'}"
    return Kind(other, "product", "products", other, None, multiples_ok=True)


def interchangeable(kind: Kind) -> bool:
    """Whether two different products of this kind can stand in for each other. Two books are
    different content, so a second book is neither a duplicate nor an alternative."""
    return kind.key != "book" and not kind.key.startswith("other-")


def group_label(kind: Kind) -> str:
    return GROUP_LABELS.get(kind.group) or kind.plural[:1].upper() + kind.plural[1:]
