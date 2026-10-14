import logging
import os

from authlib.integrations.starlette_client import OAuth

_logger = logging.getLogger(__name__)

oauth = OAuth()

_bing_tenant = (os.getenv("BING_TENANT_ID") or "common").strip() or "common"
_bing_metadata_url = (
    f"https://login.microsoftonline.com/{_bing_tenant}/v2.0/.well-known/openid-configuration"
)
_bing_scope = (os.getenv("BING_OAUTH_SCOPE") or "openid profile email offline_access").strip()


def _register_provider(name: str, client_id_env: str, client_secret_env: str, **kwargs) -> None:
    """Register an OAuth provider. If keys are missing, it registers with empty values to avoid runtime errors."""
    client_id = os.getenv(client_id_env) or ""
    client_secret = os.getenv(client_secret_env) or ""

    # We register even if empty to avoid "No such client" errors in routers.
    # The actual OAuth flow will fail gracefully at the provider level if these are empty.
    oauth.register(name=name, client_id=client_id, client_secret=client_secret, **kwargs)


_register_provider(
    "google",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def _bing_compliance_fix(session):
    """Strip id_token from Bing/Microsoft's token response.

    The Bing OAuth client shares Microsoft Entra ID's multi-tenant ("common")
    OIDC discovery which returns a template issuer ``{tenantid}``.  Authlib's
    ``parse_id_token`` will fail with ``InvalidClaimError('iss')``.  The Bing
    flow only needs the ``access_token`` for Webmaster API calls, so the
    id_token can be safely discarded (same pattern as LinkedIn).
    """

    def _strip_id_token(resp):
        original_json = resp.json

        def patched_json(**kwargs):
            data = original_json(**kwargs)
            data.pop("id_token", None)
            return data

        resp.json = patched_json
        return resp

    session.register_compliance_hook("access_token_response", _strip_id_token)


_register_provider(
    "bing",
    "BING_CLIENT_ID",
    "BING_CLIENT_SECRET",
    server_metadata_url=_bing_metadata_url,
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": _bing_scope},
    compliance_fix=_bing_compliance_fix,
)


def _bing_webmaster_compliance_fix(session):
    """Strip id_token from Bing Webmaster's token response.

    The Webmaster OAuth endpoint is plain OAuth 2.0, not OIDC; discarding any
    id_token keeps authlib off the parse_id_token path (same pattern as
    LinkedIn).
    """

    def _strip_id_token(resp):
        original_json = resp.json

        def patched_json(**kwargs):
            data = original_json(**kwargs)
            data.pop("id_token", None)
            return data

        resp.json = patched_json
        return resp

    session.register_compliance_hook("access_token_response", _strip_id_token)


# Bing Webmaster Tools OAuth (authorization-code flow against
# www.bing.com/webmasters/oauth). Deliberately separate from the "bing"
# client above, which is a Microsoft Entra registration shared with SSO and
# whose tokens Bing's Webmaster API does not accept.
_register_provider(
    "bing_webmaster",
    "BING_WEBMASTER_CLIENT_ID",
    "BING_WEBMASTER_CLIENT_SECRET",
    authorize_url="https://www.bing.com/webmasters/oauth/authorize",
    access_token_url="https://www.bing.com/webmasters/oauth/token",
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "webmaster.manage"},
    compliance_fix=_bing_webmaster_compliance_fix,
)


def _microsoft_sso_compliance_fix(session):
    """Strip id_token from Microsoft's OIDC token response.

    Microsoft Entra ID multi-tenant ("common") OIDC discovery returns a
    template issuer ``{tenantid}`` that never matches real tenant IDs in the
    token, causing authlib to raise ``InvalidClaimError('iss')``.  Stripping
    the id_token from the parsed response makes authlib skip
    ``parse_id_token`` entirely (same pattern used for LinkedIn).

    The raw id_token is preserved under ``_ms_id_token`` so
    ``_extract_microsoft_profile`` can still decode it manually.
    """

    def _move_id_token(resp):
        original_json = resp.json

        def patched_json(**kwargs):
            data = original_json(**kwargs)
            raw = data.pop("id_token", None)
            if raw:
                data["_ms_id_token"] = raw
            return data

        resp.json = patched_json
        return resp

    session.register_compliance_hook("access_token_response", _move_id_token)


_ms_sso_client_id = os.getenv("MICROSOFT_SSO_CLIENT_ID")
if not _ms_sso_client_id:
    _ms_sso_client_id = os.getenv("BING_CLIENT_ID") or ""
    if _ms_sso_client_id:
        _logger.warning(
            "MICROSOFT_SSO_CLIENT_ID not set; falling back to BING_CLIENT_ID for "
            "Microsoft SSO. Ensure the Azure app registration includes redirect URI: "
            "/api/v1/auth/microsoft/callback"
        )
_ms_sso_client_secret = (
    os.getenv("MICROSOFT_SSO_CLIENT_SECRET") or os.getenv("BING_CLIENT_SECRET") or ""
)
_ms_sso_tenant = (os.getenv("MICROSOFT_SSO_TENANT_ID") or "common").strip() or "common"
_ms_sso_metadata_url = (
    f"https://login.microsoftonline.com/{_ms_sso_tenant}/v2.0/.well-known/openid-configuration"
)

oauth.register(
    name="microsoft",
    client_id=_ms_sso_client_id,
    client_secret=_ms_sso_client_secret,
    server_metadata_url=_ms_sso_metadata_url,
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid profile email"},
    compliance_fix=_microsoft_sso_compliance_fix,
)

_register_provider(
    "github",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_kwargs={"scope": "read:user user:email"},
)


def _linkedin_compliance_fix(session):
    """Strip id_token from LinkedIn's token response.

    LinkedIn's OIDC returns an id_token but omits the ``nonce`` claim,
    breaking Authlib's ID-token validation.  Stripping the id_token
    makes Authlib skip the problematic ``parse_id_token`` path; our
    callback fetches userinfo from the /v2/userinfo API instead.
    """

    def _strip_id_token(resp):
        original_json = resp.json

        def patched_json(**kwargs):
            data = original_json(**kwargs)
            data.pop("id_token", None)
            return data

        resp.json = patched_json
        return resp

    session.register_compliance_hook("access_token_response", _strip_id_token)


_register_provider(
    "linkedin",
    "LINKEDIN_CLIENT_ID",
    "LINKEDIN_CLIENT_SECRET",
    authorize_url="https://www.linkedin.com/oauth/v2/authorization",
    access_token_url="https://www.linkedin.com/oauth/v2/accessToken",
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "openid profile email"},
    compliance_fix=_linkedin_compliance_fix,
)

_register_provider(
    "jira",
    "JIRA_CLIENT_ID",
    "JIRA_CLIENT_SECRET",
    access_token_url="https://api.atlassian.com/oauth/token",
    authorize_url="https://auth.atlassian.com/authorize",
    api_base_url="https://api.atlassian.com/",
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={
        "scope": "offline_access read:jira-user read:jira-work write:jira-work manage:jira-configuration"
    },
)

_register_provider(
    "slack",
    "SLACK_CLIENT_ID",
    "SLACK_CLIENT_SECRET",
    access_token_url="https://slack.com/api/oauth.v2.access",
    authorize_url="https://slack.com/oauth/v2/authorize",
    api_base_url="https://slack.com/api/",
    client_kwargs={"scope": "channels:read chat:write incoming-webhook"},
)
