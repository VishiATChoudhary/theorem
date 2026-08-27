"""Shared string folding for matching and dedup.

One definition so the executor's comparison semantics and the dedup
pipeline can never disagree about which names are "the same".
"""

from __future__ import annotations

import re
import unicodedata

# Latin letters with no NFKD decomposition that agents routinely
# transliterate to plain ASCII. Applied after casefold, so lowercase
# forms suffice; every target is already fully folded (idempotent).
_TRANSLIT = str.maketrans(
    {
        "ı": "i",  # noqa: RUF001 - dotless i is the point here
        "ł": "l",
        "ø": "o",
        "đ": "d",
        "ð": "d",
        "þ": "th",
        "æ": "ae",
        "œ": "oe",
        "ħ": "h",
        "ŋ": "n",
    }
)


def fold(v: object) -> object:
    """Unicode compatibility caseless matching (NFKD∘casefold twice), then
    strip combining marks and transliterate stubborn Latin letters.

    The double pass is required for idempotence: NFKD can emit new cased
    characters (e.g. math-script capital A decomposes to plain 'A').
    Non-Latin scripts pass through intact; stripping via ascii-encode
    would collapse all CJK/Cyrillic/etc. strings to "" and make them
    compare equal. Known tradeoff: combining-mark removal also drops
    meaning-bearing marks in some scripts (e.g. Devanagari nukta).
    Non-strings pass through untouched.
    """
    if not isinstance(v, str):
        return v
    s = unicodedata.normalize("NFKD", v.casefold())
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.translate(_TRANSLIT)


def norm_name(name: object) -> str:
    """Dedup normalization: folded, keeping only word characters."""
    return re.sub(r"[^\w]", "", str(fold(str(name))))
