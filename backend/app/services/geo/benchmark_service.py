from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import models
from sqlalchemy.orm import Session


class GeoBenchmarkService:
    """Compares GEO performance between two sites based on persisted audits."""

    _CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
        "local": ("near", "in ", "bucharest", "cluj", "timisoara", "iasi"),
        "comparison": ("vs", "versus", "alternative", "alternatives", "compare", "best"),
        "transactional": ("price", "pricing", "buy", "quote", "book", "order"),
        "navigational": ("login", "contact", "about", "location", "hours"),
        "informational": ("how", "what", "why", "guide", "tips", "learn"),
    }

    @staticmethod
    def _normalize_domain(value: str | None) -> str:
        if not value:
            return ""
        parsed = urlparse(
            value if value.startswith(("http://", "https://")) else f"https://{value}"
        )
        domain = (parsed.netloc or parsed.path or "").lower().removeprefix("www.")
        return domain.strip("/")

    @classmethod
    def _extract_citation_count(cls, audit: models.Audit) -> tuple[float, str]:
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        geo = report.get("geo") if isinstance(report.get("geo"), dict) else {}
        analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
        geo_visibility = (
            report.get("geo_visibility") if isinstance(report.get("geo_visibility"), dict) else {}
        )

        candidates: list[tuple[Any, str]] = [
            (geo.get("citations"), "geo.citations"),
            (geo.get("citation_count"), "geo.citation_count"),
            (geo_visibility.get("citations"), "geo_visibility.citations"),
            (report.get("citations"), "citations"),
            (geo.get("citation_share"), "geo.citation_share (fallback)"),
            (analysis.get("citation_share"), "analysis.citation_share (fallback)"),
        ]
        for value, source in candidates:
            if value is None:
                continue
            if isinstance(value, dict):
                value = value.get("score")
            try:
                return float(value), source
            except (TypeError, ValueError):
                continue
        return 0.0, "default_zero (fallback)"

    @classmethod
    def _extract_query_rows(cls, report: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        geo_visibility = report.get("geo_visibility")
        if isinstance(geo_visibility, dict) and isinstance(geo_visibility.get("results"), list):
            rows.extend(item for item in geo_visibility["results"] if isinstance(item, dict))
        if isinstance(report.get("results"), list):
            rows.extend(item for item in report["results"] if isinstance(item, dict))
        return rows

    @classmethod
    def _extract_source_domains(cls, report: dict[str, Any]) -> set[str]:
        domains: set[str] = set()

        geo = report.get("geo") if isinstance(report.get("geo"), dict) else {}
        source_fields = [
            geo.get("citation_sources"),
            geo.get("sources"),
            report.get("citation_sources"),
        ]

        for field in source_fields:
            if not isinstance(field, list):
                continue
            for item in field:
                if not isinstance(item, str):
                    continue
                domain = cls._normalize_domain(item)
                if domain:
                    domains.add(domain)

        for row in cls._extract_query_rows(report):
            citations = row.get("provider_citations")
            if not isinstance(citations, list):
                continue
            for citation in citations:
                if not isinstance(citation, str):
                    continue
                domain = cls._normalize_domain(citation)
                if domain:
                    domains.add(domain)

        return domains

    @classmethod
    def _categorize_query(cls, query: str) -> str:
        normalized = (query or "").strip().lower()
        if not normalized:
            return "unknown"
        for category, keywords in cls._CATEGORY_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                return category
        return "general"

    @classmethod
    def _build_keyword_dominance(
        cls,
        *,
        site_a_label: str,
        site_b_label: str,
        site_a_reports: list[dict[str, Any]],
        site_b_reports: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        per_category: dict[str, dict[str, int]] = defaultdict(lambda: {"site_a": 0, "site_b": 0})

        for report in site_a_reports:
            for row in cls._extract_query_rows(report):
                category = cls._categorize_query(str(row.get("query") or ""))
                if bool(row.get("brand_cited")):
                    per_category[category]["site_a"] += 1

        for report in site_b_reports:
            for row in cls._extract_query_rows(report):
                category = cls._categorize_query(str(row.get("query") or ""))
                if bool(row.get("brand_cited")):
                    per_category[category]["site_b"] += 1

        dominance_rows: list[dict[str, Any]] = []
        for category in sorted(per_category.keys()):
            scores = per_category[category]
            if scores["site_a"] > scores["site_b"]:
                dominant_site = site_a_label
            elif scores["site_b"] > scores["site_a"]:
                dominant_site = site_b_label
            else:
                dominant_site = "tie"
            dominance_rows.append(
                {
                    "category": category,
                    "site_a_cited_queries": scores["site_a"],
                    "site_b_cited_queries": scores["site_b"],
                    "dominant_site": dominant_site,
                }
            )

        return dominance_rows

    @staticmethod
    def _extract_high_risk_discrepancies(report: dict[str, Any]) -> list[dict[str, Any]]:
        hallucination = (
            report.get("hallucination") if isinstance(report.get("hallucination"), dict) else {}
        )
        claim_rows = hallucination.get("claims")
        if not isinstance(claim_rows, list):
            claim_rows = hallucination.get("claim_verifications")
        if not isinstance(claim_rows, list):
            return []

        high_risk: list[dict[str, Any]] = []
        for claim in claim_rows:
            if not isinstance(claim, dict):
                continue
            severity = str(claim.get("severity") or "").strip().lower()
            discrepancy_type = (
                str(claim.get("discrepancy_type") or "general_mismatch").strip().lower()
            )
            is_hallucination = bool(claim.get("hallucination", False))
            if not is_hallucination:
                continue
            if severity in {"high", "critical"} or discrepancy_type in {
                "pricing_mismatch",
                "features_mismatch",
                "policy_mismatch",
            }:
                high_risk.append(
                    {
                        "claim_id": str(claim.get("claim_id") or ""),
                        "claim_text": str(claim.get("claim_text") or "").strip(),
                        "severity": severity or "high",
                        "discrepancy_type": discrepancy_type,
                    }
                )
        return high_risk

    def _build_high_risk_summary(
        self,
        *,
        site_a_domain: str,
        site_b_domain: str,
        site_a_reports: list[dict[str, Any]],
        site_b_reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        site_a_claims = [
            item
            for report in site_a_reports
            for item in self._extract_high_risk_discrepancies(report)
        ]
        site_b_claims = [
            item
            for report in site_b_reports
            for item in self._extract_high_risk_discrepancies(report)
        ]

        site_a_types = defaultdict(int)
        site_b_types = defaultdict(int)
        for claim in site_a_claims:
            site_a_types[str(claim.get("discrepancy_type") or "general_mismatch")] += 1
        for claim in site_b_claims:
            site_b_types[str(claim.get("discrepancy_type") or "general_mismatch")] += 1

        all_types = sorted(set(site_a_types.keys()) | set(site_b_types.keys()))
        items: list[dict[str, Any]] = []
        for discrepancy_type in all_types:
            a_count = site_a_types.get(discrepancy_type, 0)
            b_count = site_b_types.get(discrepancy_type, 0)
            if a_count == 0 and b_count == 0:
                continue
            dominant = (
                site_a_domain
                if a_count > b_count
                else site_b_domain
                if b_count > a_count
                else "tie"
            )
            items.append(
                {
                    "discrepancy_type": discrepancy_type,
                    "severity": "high",
                    "site_a_count": a_count,
                    "site_b_count": b_count,
                    "delta": a_count - b_count,
                    "dominant_site": dominant,
                }
            )

        return {
            "site_a_total": len(site_a_claims),
            "site_b_total": len(site_b_claims),
            "items": items,
        }

    def compare_sites(
        self,
        *,
        db: Session,
        site_a_id: int,
        site_b_id: int,
        user_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[str, Any]:
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)

        site_a = db.query(models.Site).filter(models.Site.id == site_a_id).first()
        site_b = db.query(models.Site).filter(models.Site.id == site_b_id).first()
        if not site_a or not site_b:
            raise ValueError("One or both sites were not found.")

        base_audit_window_filters = (
            models.Audit.created_at >= start_at,
            models.Audit.created_at <= end_at,
        )

        # site_a is always the caller's owned site for this comparison flow.
        site_a_audits = (
            db.query(models.Audit)
            .filter(
                models.Audit.user_id == user_id,
                models.Audit.site_id == site_a_id,
                *base_audit_window_filters,
            )
            .all()
        )
        # site_b can be a monitored competitor, so do not filter by caller user_id.
        site_b_audits = (
            db.query(models.Audit)
            .filter(
                models.Audit.site_id == site_b_id,
                *base_audit_window_filters,
            )
            .all()
        )

        site_a_total = 0.0
        site_b_total = 0.0
        site_a_sources: set[str] = set()
        site_b_sources: set[str] = set()
        site_a_reports: list[dict[str, Any]] = []
        site_b_reports: list[dict[str, Any]] = []
        site_a_fallbacks: set[str] = set()
        site_b_fallbacks: set[str] = set()

        for audit in site_a_audits:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            count, source = self._extract_citation_count(audit)
            site_a_total += count
            site_a_fallbacks.add(source)
            site_a_sources.update(self._extract_source_domains(report))
            site_a_reports.append(report)

        for audit in site_b_audits:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            count, source = self._extract_citation_count(audit)
            site_b_total += count
            site_b_fallbacks.add(source)
            site_b_sources.update(self._extract_source_domains(report))
            site_b_reports.append(report)

        overlap = sorted(site_a_sources.intersection(site_b_sources))

        return {
            "site_a": {
                "id": site_a.id,
                "domain": site_a.domain,
                "audit_count": len(site_a_audits),
            },
            "site_b": {
                "id": site_b.id,
                "domain": site_b.domain,
                "audit_count": len(site_b_audits),
            },
            "citation_gap": {
                "site_a_citations": round(site_a_total, 2),
                "site_b_citations": round(site_b_total, 2),
                "delta": round(site_a_total - site_b_total, 2),
                "fallback_sources_site_a": sorted(site_a_fallbacks),
                "fallback_sources_site_b": sorted(site_b_fallbacks),
            },
            "source_overlap": {
                "count": len(overlap),
                "domains": overlap,
            },
            "keyword_dominance": self._build_keyword_dominance(
                site_a_label=site_a.domain,
                site_b_label=site_b.domain,
                site_a_reports=site_a_reports,
                site_b_reports=site_b_reports,
            ),
            "high_risk_discrepancies": self._build_high_risk_summary(
                site_a_domain=site_a.domain,
                site_b_domain=site_b.domain,
                site_a_reports=site_a_reports,
                site_b_reports=site_b_reports,
            ),
            "window": {
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
            },
        }
