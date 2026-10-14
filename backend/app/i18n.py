"""Minimal backend i18n primitives for API responses."""

from __future__ import annotations

from typing import Literal

from fastapi import Request

BackendLocale = Literal["en", "ro", "ar"]
DEFAULT_BACKEND_LOCALE: BackendLocale = "en"

EN_MESSAGES: dict[str, str] = {
    "errors.invalid_url_format": "Invalid URL format. URL must start with http:// or https://.",
    "errors.stripe_webhook_config_missing": "Stripe webhook configuration is missing.",
    "errors.stripe_signature_header_missing": "Missing Stripe-Signature header.",
    "errors.invalid_stripe_signature": "Invalid Stripe webhook signature.",
    "errors.too_many_requests": "Too Many Requests",
    "errors.too_many_requests_guest_audit": "Too Many Requests: guest audits are limited. Please try again later.",
    "errors.user_not_found": "User not found",
    "errors.user_not_found_admin": "User not found.",
    "errors.audit_not_found": "Audit not found.",
    "errors.job_not_found": "Job not found",
    "errors.save_audit_failed": "Failed to save audit to database.",
    "errors.competitor_discovery_invalid": "Invalid competitor discovery request.",
    "errors.competitor_benchmark_invalid": "Invalid competitor benchmark request.",
    "errors.geo_visibility_invalid": "Invalid geo visibility request.",
    "errors.geo_visibility_timeout": "Geo visibility provider timed out.",
    "errors.target_url_fetch_unavailable": "Unable to fetch the target URL.",
    "errors.target_url_fetch_failed": "Failed to fetch the requested URL.",
    "errors.target_url_retrieve_failed": "Unable to retrieve the requested URL.",
    "errors.notification_preferences_update_failed": "Failed to update notification preferences.",
    "errors.confirmation_required_for_delete": "Confirmation required to delete data.",
    "errors.delete_user_data_failed": "Failed to delete user data.",
    "errors.workspace_ownership_transfer_required": (
        "You own a shared workspace. Transfer its ownership to another member "
        "or remove all members before deleting your account."
    ),
    "errors.active_subscription_cancellation_required": (
        "Cancel your active subscription before deleting your account."
    ),
    "errors.billing_disabled": "Billing is currently disabled.",
    "errors.stripe_config_missing": "Stripe configuration is missing.",
    "errors.stripe_customer_missing": "Stripe customer not found for user.",
    "errors.billing_plan_unavailable": "Selected plan is not configured for checkout.",
    "errors.invalid_env_value": "Invalid {env_key} value: {raw_value}",
    "errors.plan_must_be_non_empty": "plan must be a non-empty string.",
    "errors.plan_must_be_valid": "plan must be one of plan_standard/plan_specialist/plan_executive or starter/pro/enterprise.",
    "errors.window_days_out_of_range": "window_days must be between 1 and 365.",
    "errors.page_must_be_positive": "page must be greater than 0.",
    "errors.page_size_out_of_range": "page_size must be between 1 and 100.",
    "errors.plan_plan_type_mismatch": "plan and plan_type must match when both are provided.",
    "errors.role_invalid": "role must be 'user' or 'admin'.",
    "errors.credits_must_be_non_negative": "credits must be 0 or higher.",
    "errors.delta_must_be_non_zero": "delta must be a non-zero value.",
    "errors.reason_required": "reason is required.",
    "errors.credits_cannot_go_below_zero": "credits cannot go below zero.",
    "errors.admin_self_delete_forbidden": "Admin users cannot delete their own account.",
    "errors.cache_lookup_params_required": "Provide url, provider, and tier (or an audit_id).",
    "errors.cache_lookup_provider_tier_unresolved": "Unable to resolve provider/tier for cache lookup.",
    "errors.cache_entry_not_found": "Cache entry not found.",
    "errors.cache_entry_parse_failed": "Cache entry could not be parsed.",
    "errors.cache_refresh_params_required": "Provide url, provider, and tier for targeted cache refresh or set clear_all=true.",
}

AR_MESSAGES: dict[str, str] = {
    "errors.invalid_url_format": "تنسيق عنوان URL غير صالح. يجب أن يبدأ عنوان URL بـ http:// أو https://.",
    "errors.stripe_webhook_config_missing": "إعداد webhook الخاص بـ Stripe غير موجود.",
    "errors.stripe_signature_header_missing": "ترويسة Stripe-Signature مفقودة.",
    "errors.invalid_stripe_signature": "توقيع webhook الخاص بـ Stripe غير صالح.",
    "errors.too_many_requests": "عدد كبير جداً من الطلبات",
    "errors.too_many_requests_guest_audit": "عدد كبير جداً من الطلبات: عمليات التدقيق للضيوف محدودة. يُرجى المحاولة لاحقاً.",
    "errors.user_not_found": "المستخدم غير موجود",
    "errors.user_not_found_admin": "المستخدم غير موجود.",
    "errors.audit_not_found": "التدقيق غير موجود.",
    "errors.job_not_found": "المهمة غير موجودة",
    "errors.save_audit_failed": "فشل حفظ التدقيق في قاعدة البيانات.",
    "errors.competitor_discovery_invalid": "طلب اكتشاف المنافسين غير صالح.",
    "errors.competitor_benchmark_invalid": "طلب قياس المنافسين غير صالح.",
    "errors.geo_visibility_invalid": "طلب قياس الظهور الجغرافي غير صالح.",
    "errors.geo_visibility_timeout": "انتهت مهلة موفر قياس الظهور الجغرافي.",
    "errors.target_url_fetch_unavailable": "تعذر جلب عنوان URL الهدف.",
    "errors.target_url_fetch_failed": "فشل جلب عنوان URL المطلوب.",
    "errors.target_url_retrieve_failed": "تعذر استرداد عنوان URL المطلوب.",
    "errors.notification_preferences_update_failed": "فشل تحديث تفضيلات الإشعارات.",
    "errors.confirmation_required_for_delete": "التأكيد مطلوب لحذف البيانات.",
    "errors.delete_user_data_failed": "فشل حذف بيانات المستخدم.",
    "errors.workspace_ownership_transfer_required": (
        "أنت مالك مساحة عمل مشتركة. انقل ملكيتها إلى عضو آخر " "أو أزل جميع الأعضاء قبل حذف حسابك."
    ),
    "errors.active_subscription_cancellation_required": ("ألغِ اشتراكك النشط قبل حذف حسابك."),
    "errors.billing_disabled": "الفوترة معطّلة حالياً.",
    "errors.stripe_config_missing": "إعداد Stripe غير موجود.",
    "errors.stripe_customer_missing": "لم يتم العثور على عميل Stripe للمستخدم.",
    "errors.billing_plan_unavailable": "الخطة المحددة غير مهيأة للدفع.",
    "errors.invalid_env_value": "قيمة {env_key} غير صالحة: {raw_value}",
    "errors.plan_must_be_non_empty": "يجب ألا تكون الخطة سلسلة فارغة.",
    "errors.plan_must_be_valid": "يجب أن تكون الخطة واحدة من plan_standard/plan_specialist/plan_executive أو starter/pro/enterprise.",
    "errors.window_days_out_of_range": "يجب أن تكون window_days بين 1 و 365.",
    "errors.page_must_be_positive": "يجب أن تكون الصفحة أكبر من 0.",
    "errors.page_size_out_of_range": "يجب أن يكون حجم الصفحة بين 1 و 100.",
    "errors.plan_plan_type_mismatch": "يجب أن تتطابق الخطة ونوعها عند توفرهما معاً.",
    "errors.role_invalid": "يجب أن يكون الدور 'user' أو 'admin'.",
    "errors.credits_must_be_non_negative": "يجب أن تكون الأرصدة 0 أو أكثر.",
    "errors.delta_must_be_non_zero": "يجب ألا تكون قيمة الدلتا صفراً.",
    "errors.reason_required": "السبب مطلوب.",
    "errors.credits_cannot_go_below_zero": "لا يمكن أن تصبح الأرصدة أقل من صفر.",
    "errors.admin_self_delete_forbidden": "لا يمكن للمشرفين حذف حساباتهم الخاصة.",
    "errors.cache_lookup_params_required": "وفّر url و provider و tier (أو audit_id).",
    "errors.cache_lookup_provider_tier_unresolved": "تعذر تحديد provider/tier للبحث في ذاكرة التخزين المؤقت.",
    "errors.cache_entry_not_found": "لم يتم العثور على إدخال ذاكرة التخزين المؤقت.",
    "errors.cache_entry_parse_failed": "تعذر تحليل إدخال ذاكرة التخزين المؤقت.",
    "errors.cache_refresh_params_required": "وفّر url و provider و tier للتحديث المستهدف أو اضبط clear_all=true.",
}

_BACKEND_CATALOG: dict[BackendLocale, dict[str, str]] = {
    "en": EN_MESSAGES,
    "ro": EN_MESSAGES,
    "ar": AR_MESSAGES,
}


def resolve_backend_locale(candidate: str | None) -> BackendLocale:
    if candidate and candidate.lower().startswith("ro"):
        return "ro"
    if candidate and candidate.lower().startswith("ar"):
        return "ar"
    return DEFAULT_BACKEND_LOCALE


def resolve_backend_locale_from_request(request: Request | None) -> BackendLocale:
    if request is None:
        return DEFAULT_BACKEND_LOCALE
    return resolve_backend_locale(request.headers.get("Accept-Language"))


def translate_backend_message(
    key: str,
    fallback: str,
    *,
    locale: str | None = None,
    request: Request | None = None,
    params: dict[str, str | int] | None = None,
) -> str:
    resolved_locale = (
        resolve_backend_locale(locale)
        if locale is not None
        else resolve_backend_locale_from_request(request)
    )
    template = _BACKEND_CATALOG.get(resolved_locale, {}).get(
        key,
        _BACKEND_CATALOG[DEFAULT_BACKEND_LOCALE].get(key, fallback),
    )
    if params:
        try:
            return template.format(**params)
        except Exception:
            return fallback.format(**params)
    return template
