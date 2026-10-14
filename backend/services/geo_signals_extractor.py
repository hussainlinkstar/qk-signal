"""AEX-15: Dynamic Location / Service-Area / Industry-Label Signal Extraction.

Extracts geo-relevant signals from page content and structured data using
international address patterns, service-area phrases, industry-specific
location vocabulary, and Schema.org location properties.

The extractor is called by ``score_utils.calculate_geo_score`` so that the
deterministic GEO sub-components (NAPW, spatial content) can award points
for signals that the original hardcoded US-only patterns miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GeoSignal:
    """A single detected geo signal."""

    category: str  # address | proximity | service_area | industry | schema | international
    label: str  # human-readable label
    matched_text: str  # actual matched snippet
    quality_weight: float  # 0.0-1.0 (structured > semantic > text > meta)


@dataclass
class GeoSignalResult:
    """Aggregated extraction result."""

    signals: list[GeoSignal] = field(default_factory=list)
    address_formats_detected: list[str] = field(
        default_factory=list
    )  # e.g. ["uk_postcode", "eu_postal"]
    service_area_detected: bool = False
    industry_labels_detected: list[str] = field(
        default_factory=list
    )  # e.g. ["healthcare", "retail"]
    schema_location_properties: list[str] = field(
        default_factory=list
    )  # e.g. ["PostalAddress", "areaServed"]

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def has_international_signals(self) -> bool:
        return any(s.category == "international" for s in self.signals)

    def bonus_points(self) -> float:
        """Compute an additive bonus score (0-35) for the spatial content sub-component."""
        pts = 0.0
        if self.address_formats_detected:
            pts += min(15.0, len(self.address_formats_detected) * 8.0)
        if self.service_area_detected:
            pts += 10.0
        if self.industry_labels_detected:
            pts += min(10.0, len(self.industry_labels_detected) * 5.0)
        return min(35.0, pts)


# ---------------------------------------------------------------------------
# International address format patterns
# ---------------------------------------------------------------------------

# UK postcode: SW1A 1AA, EC2R 8AH, M1 1AA, B33 8TH
_UK_POSTCODE_RE = re.compile(
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b",
    re.IGNORECASE,
)

# EU-style postal code + city: 75001 Paris, 10115 Berlin, 1010 Wien
_EU_POSTAL_RE = re.compile(
    r"\b\d{4,5}\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]{2,}\b",
)

# Romanian postal codes: 010011 Bucharest, 400001 Cluj-Napoca
_RO_POSTAL_RE = re.compile(
    r"\b\d{6}\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F\-]{2,}\b",
)

# German PLZ: DE-10115, D-10115
_DE_PREFIX_RE = re.compile(
    r"\b(?:DE?|AT|CH)[\-\s]?\d{4,5}\b",
    re.IGNORECASE,
)

# French département / cedex: 75001 PARIS CEDEX 01
_FR_CEDEX_RE = re.compile(
    r"\b\d{5}\s+[A-Z\u00C0-\u024F\s]+CEDEX(?:\s+\d{1,2})?\b",
    re.IGNORECASE,
)

# Spanish postal code: 28001 Madrid, 08001 Barcelona
_ES_POSTAL_RE = re.compile(
    r"\b(?:0[1-9]|[1-4]\d|5[0-2])\d{3}\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]{2,}\b",
)

# Generic international phone (broader than US-only)
_INTL_PHONE_RE = re.compile(
    r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{2,4}(?:[\s\-.]?\d{1,4})?",
)


# ---------------------------------------------------------------------------
# International address road keywords (multilingual)
# ---------------------------------------------------------------------------

_INTL_ADDRESS_KEYWORDS: dict[str, list[str]] = {
    "en": [
        "street",
        "avenue",
        "road",
        "suite",
        "floor",
        "building",
        "blvd",
        "drive",
        "lane",
        "court",
        "place",
        "way",
        "terrace",
        "crescent",
        "close",
        "grove",
        "highway",
        "parkway",
        "circle",
    ],
    "de": ["straße", "strasse", "str.", "weg", "platz", "gasse", "allee", "ring"],
    "fr": ["rue", "avenue", "boulevard", "place", "allée", "chemin", "impasse", "passage"],
    "es": ["calle", "avenida", "plaza", "camino", "paseo", "carrera", "vía"],
    "ro": ["strada", "bulevardul", "aleea", "calea", "soseaua", "piata", "str.", "bd.", "b-dul"],
    "it": ["via", "viale", "piazza", "corso", "vicolo", "largo"],
    "nl": ["straat", "weg", "laan", "plein", "gracht", "steeg"],
    "pt": ["rua", "avenida", "praça", "travessa", "largo", "alameda"],
}

_ALL_ADDRESS_KEYWORDS: set[str] = set()
for _lang_kws in _INTL_ADDRESS_KEYWORDS.values():
    _ALL_ADDRESS_KEYWORDS.update(kw.lower() for kw in _lang_kws)


# ---------------------------------------------------------------------------
# Expanded proximity / local-intent terms
# ---------------------------------------------------------------------------

EXPANDED_PROXIMITY_TERMS: tuple[str, ...] = (
    # Original 7
    "near me",
    "nearby",
    "local",
    "closest",
    "in the area",
    "neighborhood",
    "within miles",
    # Directional / distance
    "directions to",
    "miles from",
    "minutes from",
    "km from",
    "minutes away",
    "walking distance",
    "distance to",
    "how to get to",
    "get directions",
    # Service / availability
    "open now",
    "hours of operation",
    "opening hours",
    "business hours",
    "available in",
    "located in",
    "located at",
    "based in",
    # Geo-intent
    "zip code",
    "postal code",
    "postcode",
    "area code",
    "service area",
    "delivery area",
    "coverage area",
    # International
    "in der nähe",
    "in meiner nähe",  # DE
    "à proximité",
    "près de",  # FR
    "cerca de",
    "en la zona",  # ES
    "în apropiere",
    "în zona",  # RO
)


# ---------------------------------------------------------------------------
# Service-area detection patterns
# ---------------------------------------------------------------------------

_SERVICE_AREA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"serving\s+(?:the\s+)?(?:greater\s+)?[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+(?:\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+)*\s+(?:area|region|metro|county|district)",
        re.IGNORECASE,
    ),
    re.compile(r"available\s+in\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+", re.IGNORECASE),
    re.compile(r"(?:proudly\s+)?serving\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+", re.IGNORECASE),
    re.compile(
        r"\b[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+(?:\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+)*\s+and\s+surrounding\s+areas?\b",
        re.IGNORECASE,
    ),
    re.compile(r"throughout\s+(?:the\s+)?[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+", re.IGNORECASE),
    re.compile(r"we\s+(?:also\s+)?serve\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Industry-specific location vocabulary
# ---------------------------------------------------------------------------

_INDUSTRY_LOCATION_TERMS: dict[str, list[str]] = {
    "healthcare": [
        "clinic",
        "practice",
        "hospital",
        "medical center",
        "medical centre",
        "health center",
        "health centre",
        "dental office",
        "surgery",
        "urgent care",
        "pharmacy",
        "laboratory",
        "imaging center",
    ],
    "retail": [
        "store",
        "showroom",
        "outlet",
        "branch",
        "shop",
        "boutique",
        "warehouse",
        "distribution center",
        "pickup location",
        "retail location",
    ],
    "hospitality": [
        "hotel",
        "resort",
        "venue",
        "motel",
        "inn",
        "lodge",
        "bed and breakfast",
        "b&b",
        "guesthouse",
        "hostel",
    ],
    "education": [
        "campus",
        "school",
        "university",
        "college",
        "academy",
        "training center",
        "training centre",
        "learning center",
    ],
    "food": [
        "restaurant",
        "café",
        "cafe",
        "bistro",
        "diner",
        "bakery",
        "pizzeria",
        "bar",
        "pub",
        "brewery",
        "kitchen",
        "food truck",
    ],
    "automotive": [
        "dealership",
        "garage",
        "service center",
        "body shop",
        "car wash",
        "auto shop",
        "tire center",
    ],
    "fitness": [
        "gym",
        "fitness center",
        "fitness centre",
        "studio",
        "yoga studio",
        "dojo",
        "pool",
        "sports center",
    ],
    "professional": [
        "office",
        "firm",
        "agency",
        "headquarters",
        "hq",
        "coworking",
        "co-working",
        "workspace",
    ],
}


# ---------------------------------------------------------------------------
# Schema.org location properties
# ---------------------------------------------------------------------------

_SCHEMA_LOCATION_PROPERTIES: set[str] = {
    "PostalAddress",
    "areaServed",
    "serviceArea",
    "geo",
    "GeoCoordinates",
    "GeoShape",
    "hasMap",
    "address",
    "addressLocality",
    "addressRegion",
    "addressCountry",
    "postalCode",
    "streetAddress",
    "latitude",
    "longitude",
}


# ---------------------------------------------------------------------------
# Extractor service
# ---------------------------------------------------------------------------


class GeoSignalsExtractorService:
    """Stateless extractor, call ``extract()`` with page content + schema."""

    def extract(
        self,
        *,
        content: str = "",
        schema_analysis: dict[str, Any] | None = None,
        scrape_metadata: dict[str, Any] | None = None,
    ) -> GeoSignalResult:
        result = GeoSignalResult()
        content_lower = content.lower() if content else ""
        schema = schema_analysis or {}
        _meta = scrape_metadata or {}

        self._extract_international_addresses(content, content_lower, result)
        self._extract_expanded_proximity(content_lower, result)
        self._extract_service_areas(content, result)
        self._extract_industry_labels(content_lower, result)
        self._extract_schema_location_properties(schema, result)

        return result

    # -- International address formats ----------------------------------------

    def _extract_international_addresses(
        self,
        content: str,
        content_lower: str,
        result: GeoSignalResult,
    ) -> None:
        format_checks: list[tuple[str, re.Pattern[str], float]] = [
            ("uk_postcode", _UK_POSTCODE_RE, 0.8),
            ("eu_postal", _EU_POSTAL_RE, 0.7),
            ("ro_postal", _RO_POSTAL_RE, 0.7),
            ("de_prefix", _DE_PREFIX_RE, 0.6),
            ("fr_cedex", _FR_CEDEX_RE, 0.7),
            ("es_postal", _ES_POSTAL_RE, 0.7),
        ]
        for fmt_name, pattern, weight in format_checks:
            matches = pattern.findall(content)
            if matches:
                result.address_formats_detected.append(fmt_name)
                result.signals.append(
                    GeoSignal(
                        category="international",
                        label=fmt_name,
                        matched_text=matches[0][:60],
                        quality_weight=weight,
                    )
                )

        # International address road keywords
        for kw in _ALL_ADDRESS_KEYWORDS:
            if kw in content_lower:
                result.signals.append(
                    GeoSignal(
                        category="address",
                        label=f"intl_address_keyword:{kw}",
                        matched_text=kw,
                        quality_weight=0.5,
                    )
                )
                break  # one hit is enough for scoring

        # International phone
        intl_matches = _INTL_PHONE_RE.findall(content)
        if intl_matches:
            result.signals.append(
                GeoSignal(
                    category="address",
                    label="intl_phone",
                    matched_text=intl_matches[0][:30],
                    quality_weight=0.6,
                )
            )

    # -- Expanded proximity ---------------------------------------------------

    def _extract_expanded_proximity(
        self,
        content_lower: str,
        result: GeoSignalResult,
    ) -> None:
        for term in EXPANDED_PROXIMITY_TERMS:
            if term in content_lower:
                result.signals.append(
                    GeoSignal(
                        category="proximity",
                        label=term,
                        matched_text=term,
                        quality_weight=0.5,
                    )
                )

    # -- Service-area patterns ------------------------------------------------

    def _extract_service_areas(
        self,
        content: str,
        result: GeoSignalResult,
    ) -> None:
        for pattern in _SERVICE_AREA_PATTERNS:
            m = pattern.search(content)
            if m:
                result.service_area_detected = True
                result.signals.append(
                    GeoSignal(
                        category="service_area",
                        label="service_area_pattern",
                        matched_text=m.group()[:80],
                        quality_weight=0.7,
                    )
                )
                break  # one match is sufficient

    # -- Industry-specific labels ---------------------------------------------

    def _extract_industry_labels(
        self,
        content_lower: str,
        result: GeoSignalResult,
    ) -> None:
        for industry, terms in _INDUSTRY_LOCATION_TERMS.items():
            for term in terms:
                if term in content_lower:
                    if industry not in result.industry_labels_detected:
                        result.industry_labels_detected.append(industry)
                    result.signals.append(
                        GeoSignal(
                            category="industry",
                            label=f"{industry}:{term}",
                            matched_text=term,
                            quality_weight=0.5,
                        )
                    )
                    break  # one term per industry is enough

    # -- Schema.org location properties ---------------------------------------

    def _extract_schema_location_properties(
        self,
        schema: dict[str, Any],
        result: GeoSignalResult,
    ) -> None:
        schema_str = str(schema)
        for prop in _SCHEMA_LOCATION_PROPERTIES:
            if prop in schema_str:
                result.schema_location_properties.append(prop)
                result.signals.append(
                    GeoSignal(
                        category="schema",
                        label=f"schema:{prop}",
                        matched_text=prop,
                        quality_weight=1.0,  # structured data = highest weight
                    )
                )

        # areaServed in detected_schema_types list or raw schema string
        detected_types = schema.get("detected_schema_types", [])
        for dtype in detected_types:
            dtype_lower = str(dtype).lower()
            if "service" in dtype_lower or "area" in dtype_lower:
                if "areaServed" not in result.schema_location_properties:
                    result.schema_location_properties.append("areaServed_type")
                    result.signals.append(
                        GeoSignal(
                            category="schema",
                            label=f"schema_type:{dtype}",
                            matched_text=dtype,
                            quality_weight=1.0,
                        )
                    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

geo_signals_extractor_service = GeoSignalsExtractorService()
