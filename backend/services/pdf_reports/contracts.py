from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandingConfig:
    title: str
    primary_color: str
    generated_date: str
    language: str = "en"
    logo_data_url: str | None = None
    company_name: str | None = None
    secondary_color: str | None = None
    vendor_name: str = "Qiko Signal"
    is_white_label: bool = False
    show_powered_by: bool = False
    report_type: str | None = None
    report_kind: str | None = None
    branding_mode: str | None = None
    competitor_mode: str | None = None
    hide_credit_cost: bool | None = None
    footer_text: str | None = None
    custom_footer_text: str | None = None
    show_platform_branding: bool | None = None
