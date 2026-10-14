"""Geographic parameter mapping for outbound SerpAPI search requests.

SerpAPI does not accept an ISO 3166-1 alpha-2 country code in ``location``.
Per the Google Search API reference, ``location`` "defines from where you want
the search to originate" and must resolve against SerpAPI's own locations
database (``/locations.json``), whose entries are canonical names such as
``Austin,Texas,United States``. Anything it cannot resolve is rejected before
the search runs:

    HTTP 400 {"error": "Unsupported `us` location - location parameter."}

The country belongs in ``gl``, documented as "the country to use for the Google
search. It's a two-letter country code (e.g. ``us``)". The language belongs in
``hl``, a two-letter language code. ``location``, ``gl`` and ``hl`` are all
optional, and the same reference recommends ``gl`` for country-level filtering
and ``location`` at city level.

So a project market such as ``us`` must travel as ``gl=us``, never as
``location=us``, and ``location`` is only ever populated from a value that
looks like a real place name.
"""

from __future__ import annotations

import re

# ISO 3166-1 alpha-2 shaped token, which is exactly what ``gl`` expects, and
# also the shape ``hl`` expects for a language.
_TWO_LETTER_CODE_RE = re.compile(r"^[a-z]{2}$")
# Values such as ``en-us`` (locale) or ``co-uk`` (derived from a ccSLD host)
# carry the country in the trailing segment.
_COMPOSITE_MARKET_RE = re.compile(r"^([a-z]{2,3})[-_]([a-z]{2})$")
# Markets that express "no geography", which must not reach SerpAPI at all.
_UNSPECIFIED_MARKETS = frozenset({"global", "worldwide", "international", "any", "none", "n/a"})


def looks_like_country_code(value: str | None) -> bool:
    """True when *value* is a bare two-letter country code such as ``us``."""
    return bool(_TWO_LETTER_CODE_RE.match(str(value or "").strip().lower()))


def resolve_country_code(value: str | None) -> str | None:
    """Extract a ``gl``-compatible country code from a market string.

    Handles the shapes this codebase produces: ``us``, ``en-us``, ``co-uk``.
    Returns ``None`` for place names and for "no geography" markers.
    """
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in _UNSPECIFIED_MARKETS:
        return None
    if _TWO_LETTER_CODE_RE.match(normalized):
        return normalized
    composite = _COMPOSITE_MARKET_RE.match(normalized)
    if composite:
        return composite.group(2)
    return None


def build_serpapi_geo_params(
    market: str | None,
    *,
    allow_location: bool = False,
    language: str | None = None,
) -> dict[str, str]:
    """Map a market/location string onto SerpAPI's geographic parameters.

    * A country code (``us``, ``en-us``, ``co-uk``) becomes ``gl``.
    * A place name (``Bucharest``) becomes ``location``, but only when
      *allow_location* is set, i.e. when the caller's value really is a
      location and not a market identifier.
    * ``global`` and friends produce no geographic parameter at all.
    * *language*, when it is a two-letter code, becomes ``hl``.
    """
    params: dict[str, str] = {}

    raw = str(market or "").strip()
    country = resolve_country_code(raw)
    if country:
        params["gl"] = country
    elif allow_location and raw and raw.lower() not in _UNSPECIFIED_MARKETS:
        params["location"] = raw

    normalized_language = str(language or "").strip().lower().replace("_", "-").split("-")[0]
    if _TWO_LETTER_CODE_RE.match(normalized_language):
        params["hl"] = normalized_language

    return params
