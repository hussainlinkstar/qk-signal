import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["SSM_ENABLED"] = "0"

from services.report_i18n_service import (
    get_email_copy,
    get_report_label,
    is_cjk_report_language,
    is_rtl_report_language,
    normalize_report_language,
)


def test_normalize_report_language_supports_region_codes_and_fallback() -> None:
    assert normalize_report_language("ro-RO") == "ro"
    assert normalize_report_language("ja-JP") == "ja"
    assert normalize_report_language("unknown") == "en"
    assert normalize_report_language(None) == "en"
    assert is_cjk_report_language("ja-JP") is True
    assert is_cjk_report_language("ro") is False


def test_get_email_copy_returns_localized_subject_and_common_copy() -> None:
    email_copy = get_email_copy(
        "ro-RO",
        "audit.completed",
        context={
            "target_host": "example.com",
            "brand_name": "Qiko Signal",
        },
    )

    assert email_copy["subject"] == "Audit finalizat pentru example.com"
    assert email_copy["notification"] == "Notificare"


def test_normalize_arabic_and_regional_variants() -> None:
    assert normalize_report_language("ar") == "ar"
    assert normalize_report_language("ar-AE") == "ar"
    assert normalize_report_language("ar-SA") == "ar"
    assert normalize_report_language("ar-EG") == "ar"
    assert normalize_report_language("AR-ae") == "ar"
    assert is_rtl_report_language("ar") is True
    assert is_rtl_report_language("ar-SA") is True
    assert is_rtl_report_language("en") is False
    assert is_rtl_report_language("ja") is False
    assert is_rtl_report_language(None) is False
    # Existing languages unaffected.
    assert is_cjk_report_language("ar") is False
    assert normalize_report_language("en") == "en"
    assert normalize_report_language("ro-RO") == "ro"


def test_arabic_report_labels_and_fallbacks() -> None:
    assert get_report_label("ar", "pdf.executive_summary") == "الملخص التنفيذي"
    assert get_report_label("ar-AE", "pdf.executive_summary") == "الملخص التنفيذي"
    assert get_report_label("ar", "pdf.score_label") == "الدرجة"
    assert get_report_label("ar", "pdf.withheld_sections_title") == (
        "أقسام غير مضمّنة في هذا التقرير"
    )
    # Placeholder params still interpolate inside Arabic copy.
    assert (
        get_report_label("ar", "pdf.withheld_section_upgrade_hint", params={"plan": "Specialist"})
        == "متوفر في خطة Specialist"
    )
    # Missing keys fall back to the English catalog, never to the raw key.
    assert get_report_label("ar", "pdf.untranslated_key", default="Fallback Text") == (
        "Fallback Text"
    )
    assert "pdf.untranslated_key" not in get_report_label(
        "ar", "pdf.untranslated_key", default="Fallback Text"
    )
    # English render unchanged by the new catalog.
    assert get_report_label("en", "pdf.executive_summary") == "Executive Summary"


def test_arabic_backend_locale_messages() -> None:
    from app.i18n import resolve_backend_locale, translate_backend_message

    assert resolve_backend_locale("ar-SA") == "ar"
    assert resolve_backend_locale("ar") == "ar"
    assert resolve_backend_locale("en-US") == "en"

    message = translate_backend_message("errors.audit_not_found", "Audit not found.", locale="ar")
    assert message == "التدقيق غير موجود."
    # Error keys remain machine-readable; only the human message is localized.
    message = translate_backend_message("errors.user_not_found", "User not found", locale="ar-AE")
    assert message == "المستخدم غير موجود"
    # Unknown keys still return the caller's fallback.
    assert (
        translate_backend_message("errors.no_such_key", "Plain fallback.", locale="ar")
        == "Plain fallback."
    )
