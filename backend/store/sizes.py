"""Product sizes and the shopper's saved sizes.

A sized product lists its sizes in `attributes["sizes"]`, e.g. "UK 6, UK 7, UK 8" or "S, M, L".
The size system is read from the values themselves, so no extra field is needed:

    shoe        "UK 9"         matched against the saved UK shoe size
    shoe_range  "UK 7-11"      socks: the range that contains the saved shoe size
    top         "M"            matched against the saved clothing size (XS to XXL)
    waist       "32"           matched against the saved waist in inches
    age         "Age 4-5"      kids' sizes; no saved size to compare with
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOP_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
_SHOE_RE = re.compile(r"^UK (\d{1,2})$")
_SHOE_RANGE_RE = re.compile(r"^UK (\d{1,2})-(\d{1,2})$")
SYSTEM_LABELS = {"shoe": "shoe size", "shoe_range": "shoe size", "top": "clothing size", "waist": "waist size", "age": "age range"}


def product_sizes(product) -> list[str]:
    raw = (getattr(product, "attributes", None) or {}).get("sizes", "")
    return [s.strip() for s in str(raw).split(",") if s.strip()]


def size_system(sizes: list[str]) -> str | None:
    if not sizes:
        return None
    if all(_SHOE_RE.match(s) for s in sizes):
        return "shoe"
    if all(_SHOE_RANGE_RE.match(s) for s in sizes):
        return "shoe_range"
    if all(s in TOP_SIZES for s in sizes):
        return "top"
    if all(s.isdigit() for s in sizes):
        return "waist"
    if all(s.lower().startswith("age") for s in sizes):
        return "age"
    return "other"


@dataclass
class SizePrefs:
    """Sizes the shopper has saved or stated. Any of them may be unknown."""

    shoe_uk: int | None = None
    top: str | None = None
    waist_in: int | None = None

    @classmethod
    def from_profile(cls, profile) -> "SizePrefs":
        if profile is None:
            return cls()
        return cls(shoe_uk=profile.shoe_size_uk, top=profile.clothing_size or None, waist_in=profile.waist_in)

    def merged(self, stated: "SizePrefs") -> "SizePrefs":
        """Sizes stated for this purchase win over saved ones."""
        return SizePrefs(shoe_uk=stated.shoe_uk or self.shoe_uk, top=stated.top or self.top, waist_in=stated.waist_in or self.waist_in)

    def is_empty(self) -> bool:
        return not (self.shoe_uk or self.top or self.waist_in)


def preferred_size(prefs: SizePrefs, sizes: list[str]) -> str | None:
    """The size this shopper would pick from `sizes`, written exactly like the product's size, or None."""
    system = size_system(sizes)
    if system == "shoe" and prefs.shoe_uk:
        return f"UK {prefs.shoe_uk}"
    if system == "shoe_range" and prefs.shoe_uk:
        for s in sizes:
            low, high = map(int, _SHOE_RANGE_RE.match(s).groups())
            if low <= prefs.shoe_uk <= high:
                return s
        return f"UK {prefs.shoe_uk}"  # outside every range: reported as unavailable
    if system == "top" and prefs.top:
        return prefs.top
    if system == "waist" and prefs.waist_in:
        return str(prefs.waist_in)
    return None


_STATED_SHOE = re.compile(r"\b(?:uk\s?|shoe\s?size\s?|size\s?uk\s?)(\d{1,2})\b", re.I)
_STATED_TOP = re.compile(r"\b(?:size\s?|wear\s(?:an?\s)?|i(?:'m| am) an?\s)(XXL|XL|XS|S|M|L)\b", re.I)
_STATED_WAIST = re.compile(r"\b(?:waist\s?(\d{2})|(\d{2})\s?(?:inch|in|\")?\s?waist)\b", re.I)


def stated_sizes(text: str) -> SizePrefs:
    """Sizes written in the shopper's own words, e.g. "UK 10", "size M", "32 waist"."""
    text = text or ""
    shoe = _STATED_SHOE.search(text)
    top = _STATED_TOP.search(text)
    waist = _STATED_WAIST.search(text)
    return SizePrefs(
        shoe_uk=int(shoe.group(1)) if shoe and 1 <= int(shoe.group(1)) <= 15 else None,
        top=top.group(1).upper() if top else None,
        waist_in=int(next(g for g in waist.groups() if g)) if waist else None,
    )
