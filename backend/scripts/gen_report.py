"""CLI helper to render a white-label audit PDF from JSON input.

Usage:
python backend/scripts/gen_report.py --input /path/to/payload.json --output report.pdf
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from services.pdf_report_renderer import BrandingConfig, render_white_label_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate white-label audit PDF from JSON payload")
    parser.add_argument("--input", required=True, help="Path to JSON payload file")
    parser.add_argument("--output", required=True, help="Output PDF path")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text())

    branding = BrandingConfig(
        title=payload.get("title") or payload.get("agency_name") or "White-Label Audit Report",
        primary_color=payload.get("primary_color") or "#00F2FF",
        generated_date=payload.get("report_date")
        or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        logo_data_url=payload.get("logo_data_url"),
    )

    pdf_bytes = render_white_label_pdf(
        audit_id=int(payload["audit_id"]),
        audit_url=str(payload.get("audit_url") or ""),
        geo_score=float(payload.get("geo_score") or 0),
        highlights=list(payload.get("highlights") or []),
        full_report=dict(payload.get("full_report") or {}),
        branding=branding,
        include_competitor_analysis=bool(payload.get("include_competitor_analysis", False)),
    )

    output_path = Path(args.output)
    output_path.write_bytes(pdf_bytes)
    print(f"Saved PDF report to {output_path}")


if __name__ == "__main__":
    main()
