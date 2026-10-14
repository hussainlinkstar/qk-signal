"""Canonical auth dependency helpers used across backend routers."""

from auth.token_verifier import get_current_admin_user, get_current_staff_user, get_current_user


# Backwards-compatible alias used by existing routers.
get_current_user_from_token = get_current_user

__all__ = [
    "get_current_user",
    "get_current_user_from_token",
    "get_current_admin_user",
    "get_current_staff_user",
]
