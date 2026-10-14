#!/usr/bin/env python3
"""
scripts/setup_analytics_production.py

Fully interactive production setup script that auto-provisions:
  1. Google Analytics 4 — property + web data stream + enhanced config
     (14-month data retention, enhanced measurement, key events,
     custom dimensions, Search Console linking)
  2. Google Tag Manager — account + web container + GA4 tag
  3. Google Search Console — add & verify site, submit sitemap
  4. Bing Webmaster Tools — add & verify site, submit sitemap + key URLs

Auto-detects SSH/VPS environment, checks all prerequisites, prompts for
missing credentials, guides through OAuth tunnel setup, allows skipping
individual services, and rebuilds the frontend container after writing
env vars.

Usage (on VPS over SSH — auto-detects headless mode):
    cd /opt/docker/thothgraph
    python3 scripts/setup_analytics_production.py

Usage (local with browser):
    python scripts/setup_analytics_production.py

All flags are optional — the script auto-detects and prompts for everything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
SCRIPT_VENV_DIR = PROJECT_ROOT / ".analytics-setup-venv"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ─── Ensure dependencies ───────────────────────────────────────────────
REQUIRED_PACKAGES = [
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
    "python-dotenv",
    "requests",
]


def _running_in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or bool(os.getenv("VIRTUAL_ENV"))


def _bootstrap_script_venv(missing: list[str]) -> None:
    venv_python = SCRIPT_VENV_DIR / "bin" / "python"
    if not venv_python.exists():
        print(f"\nCreating dedicated virtualenv for analytics setup at {SCRIPT_VENV_DIR}")
        subprocess.check_call([sys.executable, "-m", "venv", str(SCRIPT_VENV_DIR)])

    # Ensure pip is available inside the venv (some distros strip ensurepip)
    try:
        subprocess.check_call([str(venv_python), "-m", "pip", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("  pip not found in venv — bootstrapping via ensurepip / get-pip.py …")
        try:
            subprocess.check_call([str(venv_python), "-m", "ensurepip", "--upgrade"])
        except subprocess.CalledProcessError:
            # ensurepip missing (common on Debian/Ubuntu minimal) → use get-pip.py
            import urllib.request
            get_pip = SCRIPT_VENV_DIR / "get-pip.py"
            urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", str(get_pip))
            subprocess.check_call([str(venv_python), str(get_pip)])

    subprocess.check_call([str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "--quiet", *missing])

    current_python = Path(sys.executable).absolute()
    if current_python != venv_python.absolute():
        print(f"Re-launching analytics setup inside {venv_python}\n")
        os.execve(
            str(venv_python),
            [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            os.environ.copy(),
        )


def ensure_packages() -> None:
    """Pip-install missing deps at runtime so the script is self-contained."""
    missing: list[str] = []
    import importlib

    package_map = {
        "google-api-python-client": "googleapiclient",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "google-auth-httplib2": "google_auth_httplib2",
        "python-dotenv": "dotenv",
        "requests": "requests",
    }
    for pip_name, import_name in package_map.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"\n⏳ Installing missing packages: {', '.join(missing)}")
        if _running_in_virtualenv():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", *missing]
            )
        else:
            _bootstrap_script_venv(missing)
        print("✅ Packages installed.\n")


ensure_packages()

from core.env_bootstrap import bootstrap_environment  # noqa: E402
from dotenv import dotenv_values, load_dotenv  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402
import requests  # noqa: E402

# ─── Constants ──────────────────────────────────────────────────────────
ROOT_ENV = PROJECT_ROOT / ".env"
FRONTEND_ENV = PROJECT_ROOT / "frontend" / ".env"
BACKEND_ENV = PROJECT_ROOT / "backend" / ".env"

# Google OAuth scopes needed for all 3 services
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/analytics.edit",       # GA4 Admin
    "https://www.googleapis.com/auth/tagmanager.edit.containers",  # GTM
    "https://www.googleapis.com/auth/tagmanager.manage.accounts",  # GTM
    "https://www.googleapis.com/auth/webmasters",           # Search Console
    "https://www.googleapis.com/auth/siteverification",     # Search Console verification token
]

# Bing Webmaster API
BING_WEBMASTER_API = "https://ssl.bing.com/webmaster/api.svc/json"

# ─── Colors ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
NC = "\033[0m"


def bootstrap_runtime_environment() -> None:
    """Load local dotenv files first, then overlay AWS SSM via bootstrap_environment().

    bootstrap_environment() applies the AWS SSM Parameter Store overlay when it is
    configured/available and otherwise leaves the loaded dotenv values in place.
    """
    for env_path in (ROOT_ENV, BACKEND_ENV, FRONTEND_ENV):
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)

    bootstrap_environment()


bootstrap_runtime_environment()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision production analytics and webmaster services.")
    parser.add_argument("--domain", help="Target domain. Defaults to DOMAIN env or thothgraph.com.")
    parser.add_argument(
        "--site-url",
        help="Canonical site URL. Defaults to APP_BASE_URL or https://<domain>.",
    )
    parser.add_argument(
        "--write-targets",
        default="root,frontend",
        help="Comma-separated env files to update: root, frontend.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Do not open a browser for Google OAuth. Auto-detected when SSH_CONNECTION is set.",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Do not rebuild the frontend container after writing env vars.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip interactive prompts and run all services.",
    )
    parser.add_argument(
        "--google-port",
        type=int,
        default=8085,
        help="Loopback port used by the Google OAuth callback server.",
    )
    return parser.parse_args()


def resolve_runtime_targets(args: argparse.Namespace) -> tuple[str, str, list[Path]]:
    env_domain = (os.getenv("DOMAIN") or "").strip()
    domain = (args.domain or env_domain or "thothgraph.com").strip().lower()

    env_site_url = (os.getenv("APP_BASE_URL") or "").strip()
    site_url = (args.site_url or env_site_url or f"https://{domain}").strip().rstrip("/")
    parsed = urlparse(site_url)
    if parsed.scheme and parsed.netloc:
        domain = parsed.netloc
    elif domain:
        site_url = f"https://{domain}"

    target_map = {
        "root": ROOT_ENV,
        "frontend": FRONTEND_ENV,
    }
    write_targets: list[Path] = []
    for raw_target in args.write_targets.split(","):
        target_key = raw_target.strip().lower()
        if not target_key:
            continue
        target_path = target_map.get(target_key)
        if target_path is None:
            raise SystemExit(f"Unknown --write-targets value: {raw_target}")
        write_targets.append(target_path)

    if not write_targets:
        write_targets = [ROOT_ENV, FRONTEND_ENV]

    return domain, site_url, write_targets


def banner(domain: str, write_targets: list[Path]) -> None:
    rendered_targets = ", ".join(str(path) for path in write_targets)
    print(f"""
{CYAN}╔══════════════════════════════════════════════════════════════════╗
║{NC}  {BOLD}Qiko Signal — Automated Analytics & Webmaster Provisioning{NC}   {CYAN}║
╚══════════════════════════════════════════════════════════════════╝{NC}

  Domain:  {GREEN}{domain}{NC}
  Env:     {GREEN}{rendered_targets}{NC}
""")


def separator(label: str = "") -> None:
    line = "─" * 64
    if label:
        print(f"\n{CYAN}{line}{NC}")
        print(f"  {BOLD}{label}{NC}")
        print(f"{CYAN}{line}{NC}\n")
    else:
        print(f"\n{CYAN}{line}{NC}\n")


# ─── Env helpers ────────────────────────────────────────────────────────

def load_env_files() -> dict[str, str | None]:
    """Load root env plus optional backend overlay so the script can run before containers start."""
    combined: dict[str, str | None] = {}
    for env_path in (ROOT_ENV, BACKEND_ENV):
        if env_path.exists():
            combined.update(dotenv_values(env_path))
    return combined


def get_env(key: str, env_dict: dict[str, str | None]) -> str:
    """Get from env_dict, then os.environ, or raise."""
    val = env_dict.get(key) or os.environ.get(key) or ""
    return val.strip()


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Upsert key=value pairs in the selected env file."""
    if not env_path.exists():
        env_path.touch()

    content = env_path.read_text(encoding="utf-8")

    for key, value in updates.items():
        if not value:
            continue
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f"{key}={value}", content)
            print(f"  {GREEN}✓ Updated{NC} {env_path}: {key}={value}")
        else:
            content = content.rstrip() + f"\n\n# [AUTO] Set by setup_analytics_production.py\n{key}={value}\n"
            print(f"  {GREEN}✓ Added{NC}  {env_path}: {key}={value}")

    env_path.write_text(content, encoding="utf-8")


def update_env_files(write_targets: list[Path], updates: dict[str, str]) -> None:
    for env_path in write_targets:
        update_env_file(env_path, updates)


def infer_google_client_project(creds) -> str:
    client_id = str(getattr(creds, "client_id", "") or "").strip()
    if not client_id or "-" not in client_id:
        return ""
    return client_id.split("-", 1)[0]


def is_google_api_disabled_error(exc: Exception) -> bool:
    if not isinstance(exc, HttpError):
        return False
    message = str(exc).lower()
    return (
        "accessnotconfigured" in message
        or "has not been used in project" in message
        or "is disabled" in message
    )


def print_google_api_enable_hint(api_service: str, creds) -> None:
    project = infer_google_client_project(creds)
    if project:
        url = (
            f"https://console.developers.google.com/apis/api/"
            f"{api_service}/overview?project={project}"
        )
    else:
        url = f"https://console.developers.google.com/apis/api/{api_service}/overview"

    print(f"  {YELLOW}→ Enable {api_service} and retry this step:{NC} {url}")
    print(f"  {YELLOW}  Wait 2-5 minutes after enabling for propagation.{NC}")


# ─── Google OAuth2 ──────────────────────────────────────────────────────

def google_oauth_flow(client_id: str, client_secret: str, *, headless: bool, port: int):
    """Run installed-app OAuth flow, return google.oauth2 Credentials."""
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{port}"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=GOOGLE_SCOPES)
    if headless:
        print(f"  {YELLOW}▸ Headless Google OAuth mode enabled.{NC}")
        print(
            f"  {YELLOW}  If you are on an SSH session, create a local tunnel first:{NC} "
            f"{BOLD}ssh -L {port}:127.0.0.1:{port} <user>@<vps>{NC}"
        )
        print(f"  {YELLOW}  The script will print a Google consent URL instead of opening a browser.{NC}")
    else:
        print(f"  {YELLOW}▸ Opening browser for Google sign-in...{NC}")

    creds = flow.run_local_server(
        port=port,
        prompt="consent",
        open_browser=not headless,
        authorization_prompt_message="Open this URL to authorize the Google setup flow:\n{url}\n",
        success_message="Google authorization complete. You can return to the VPS shell.",
    )
    print(f"  {GREEN}✓ Google OAuth authorized.{NC}\n")
    return creds


# ─── GA4 Admin ──────────────────────────────────────────────────────────

def setup_ga4(creds, *, domain: str, site_url: str, step_label: str = "") -> tuple[str, str]:
    """Create or reuse GA4 property + web stream, then configure enhanced
    production settings (data retention, enhanced measurement, key events,
    custom dimensions, Search Console link).  Returns (property_id, measurement_id)."""
    separator(step_label or "Google Analytics 4")

    # v1alpha is a superset of v1beta and exposes enhanced measurement,
    # data-retention, search-console linking, and audience management.
    use_alpha = False
    try:
        service = build("analyticsadmin", "v1alpha", credentials=creds)
        use_alpha = True
    except Exception:
        print(f"  {YELLOW}⚠ v1alpha API unavailable — using v1beta (enhanced config will be skipped).{NC}")
        service = build("analyticsadmin", "v1beta", credentials=creds)

    # ── List accounts ───────────────────────────────────────────────
    accounts_response = service.accounts().list().execute()
    accounts = accounts_response.get("accounts", [])
    if not accounts:
        print(f"  {RED}✗ No GA accounts found. Creating is not supported via API for first account.{NC}")
        print(f"  {YELLOW}  → Go to https://analytics.google.com and create your first account.{NC}")
        print(f"  {YELLOW}  → Then re-run this script.{NC}")
        return "", ""

    account = accounts[0]
    account_name = account["name"]
    print(f"  Using GA account: {CYAN}{account.get('displayName', account_name)}{NC}")

    property_id = ""
    measurement_id = ""
    stream_name = ""  # full resource path, e.g. properties/123/dataStreams/456

    # ── Check if property already exists ────────────────────────────
    props_response = service.properties().list(filter=f'parent:{account_name}').execute()
    existing_props = props_response.get("properties", [])
    for prop in existing_props:
        if domain in prop.get("displayName", ""):
            property_id = prop["name"].split("/")[-1]
            print(f"  {YELLOW}⊘ Property already exists:{NC} {prop.get('displayName')} (ID: {property_id})")
            streams = service.properties().dataStreams().list(parent=prop["name"]).execute()
            for stream in streams.get("dataStreams", []):
                if stream.get("type") == "WEB_DATA_STREAM":
                    measurement_id = stream.get("webStreamData", {}).get("measurementId", "")
                    stream_name = stream.get("name", "")
                    print(f"  {GREEN}✓ Existing Measurement ID:{NC} {measurement_id}")
                    break
            break

    # ── Create property + stream if needed ──────────────────────────
    if not property_id:
        property_body = {
            "displayName": f"Qiko Signal ({domain})",
            "timeZone": "Europe/Bucharest",
            "currencyCode": "EUR",
            "parent": account_name,
        }
        created = service.properties().create(body=property_body).execute()
        property_name = created["name"]
        property_id = property_name.split("/")[-1]
        print(f"  {GREEN}✓ Created GA4 Property:{NC} {created.get('displayName')} (ID: {property_id})")

        stream_body = {
            "type": "WEB_DATA_STREAM",
            "displayName": "Qiko Signal Production",
            "webStreamData": {"defaultUri": site_url},
        }
        stream = service.properties().dataStreams().create(
            parent=property_name, body=stream_body
        ).execute()
        measurement_id = stream.get("webStreamData", {}).get("measurementId", "")
        stream_name = stream.get("name", "")
        print(f"  {GREEN}✓ Created Web Stream:{NC} Measurement ID = {BOLD}{measurement_id}{NC}")

    # ── Enhanced GA4 configuration (v1alpha only, non-fatal) ────────
    if property_id and use_alpha:
        prop_res = f"properties/{property_id}"
        print(f"\n  {BOLD}Configuring enhanced GA4 settings…{NC}")
        _ga4_set_data_retention(service, prop_res)
        if stream_name:
            _ga4_set_enhanced_measurement(service, stream_name)
        _ga4_create_key_events(service, prop_res)
        _ga4_create_custom_dimensions(service, prop_res)
        _ga4_link_search_console(service, prop_res, site_url)

    return property_id, measurement_id


# ─── GA4 Enhanced Configuration Helpers ─────────────────────────────────

def _ga4_set_data_retention(service, property_name: str) -> None:
    """Set event data retention to 14 months (maximum for standard properties)."""
    try:
        current = service.properties().getDataRetentionSettings(
            name=f"{property_name}/dataRetentionSettings"
        ).execute()
        if current.get("eventDataRetention") == "FOURTEEN_MONTHS":
            print(f"  {YELLOW}⊘ Data retention already set to 14 months.{NC}")
            return

        service.properties().updateDataRetentionSettings(
            name=f"{property_name}/dataRetentionSettings",
            updateMask="eventDataRetention,resetUserDataOnNewActivity",
            body={
                "eventDataRetention": "FOURTEEN_MONTHS",
                "resetUserDataOnNewActivity": True,
            },
        ).execute()
        print(f"  {GREEN}✓ Data retention set to 14 months.{NC}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not set data retention: {e}{NC}")


def _ga4_set_enhanced_measurement(service, stream_name: str) -> None:
    """Enable all enhanced measurement settings on the web data stream."""
    try:
        em_name = f"{stream_name}/enhancedMeasurementSettings"
        current = service.properties().dataStreams().getEnhancedMeasurementSettings(
            name=em_name
        ).execute()

        desired_toggles = [
            "streamEnabled", "scrollsEnabled", "outboundClicksEnabled",
            "siteSearchEnabled", "videoEngagementEnabled", "fileDownloadsEnabled",
            "pageChangesEnabled", "formInteractionsEnabled",
        ]
        if all(current.get(t) for t in desired_toggles):
            print(f"  {YELLOW}⊘ Enhanced measurement already fully enabled.{NC}")
            return

        body = {t: True for t in desired_toggles}
        body["searchQueryParameter"] = current.get("searchQueryParameter") or "q,s,search,query,keyword"

        service.properties().dataStreams().updateEnhancedMeasurementSettings(
            name=em_name,
            updateMask=",".join(desired_toggles) + ",searchQueryParameter",
            body=body,
        ).execute()
        print(f"  {GREEN}✓ Enhanced measurement enabled (scrolls, clicks, search, video, downloads, forms).{NC}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not configure enhanced measurement: {e}{NC}")


def _ga4_create_key_events(service, property_name: str) -> None:
    """Create key events for important user interactions."""
    try:
        existing_response = service.properties().keyEvents().list(
            parent=property_name
        ).execute()
        existing_names = {
            ke.get("eventName") for ke in existing_response.get("keyEvents", [])
        }
    except Exception:
        existing_names = set()

    desired_events = [
        ("sign_up", "ONCE_PER_EVENT"),
        ("login", "ONCE_PER_SESSION"),
        ("generate_lead", "ONCE_PER_EVENT"),   # audit form submission
        ("begin_checkout", "ONCE_PER_EVENT"),   # plan upgrade initiated
        ("purchase", "ONCE_PER_EVENT"),         # subscription completed
    ]

    created = 0
    skipped = 0
    for event_name, counting in desired_events:
        if event_name in existing_names:
            skipped += 1
            continue
        try:
            service.properties().keyEvents().create(
                parent=property_name,
                body={"eventName": event_name, "countingMethod": counting},
            ).execute()
            created += 1
        except Exception:
            pass

    if created:
        print(f"  {GREEN}✓ Created {created} key event(s).{NC}")
    if skipped:
        print(f"  {YELLOW}⊘ {skipped} key event(s) already exist.{NC}")
    if not created and not skipped:
        print(f"  {YELLOW}⊘ No key events configured.{NC}")


def _ga4_create_custom_dimensions(service, property_name: str) -> None:
    """Create custom dimensions for Qiko Signal-specific analytics."""
    try:
        existing_response = service.properties().customDimensions().list(
            parent=property_name
        ).execute()
        existing_params = {
            cd.get("parameterName")
            for cd in existing_response.get("customDimensions", [])
        }
    except Exception:
        existing_params = set()

    desired_dimensions = [
        ("user_plan", "User Plan", "EVENT",
         "Subscription plan of the user (plan_standard, plan_specialist, etc.)"),
        ("audit_type", "Audit Type", "EVENT",
         "Type of audit run (seo, geo, aeo, full)"),
        ("audit_provider", "Audit Provider", "EVENT",
         "AI provider used for audit (google, openai, anthropic)"),
        ("content_group", "Content Group", "EVENT",
         "Content group for page categorization"),
    ]

    created = 0
    skipped = 0
    for param_name, display_name, scope, description in desired_dimensions:
        if param_name in existing_params:
            skipped += 1
            continue
        try:
            service.properties().customDimensions().create(
                parent=property_name,
                body={
                    "parameterName": param_name,
                    "displayName": display_name,
                    "scope": scope,
                    "description": description,
                },
            ).execute()
            created += 1
        except Exception:
            pass

    if created:
        print(f"  {GREEN}✓ Created {created} custom dimension(s).{NC}")
    if skipped:
        print(f"  {YELLOW}⊘ {skipped} custom dimension(s) already exist.{NC}")


def _ga4_link_search_console(service, property_name: str, site_url: str) -> None:
    """Link GA4 property to Google Search Console."""
    try:
        existing = service.properties().searchConsoleLinks().list(
            parent=property_name
        ).execute()
        for link in existing.get("searchConsoleLinks", []):
            if site_url in link.get("siteUrl", ""):
                print(f"  {YELLOW}⊘ Search Console already linked to GA4.{NC}")
                return
    except Exception:
        pass

    try:
        service.properties().searchConsoleLinks().create(
            parent=property_name,
            body={"siteUrl": site_url},
        ).execute()
        print(f"  {GREEN}✓ Linked Search Console ({site_url}) to GA4 property.{NC}")
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "exists" in msg:
            print(f"  {YELLOW}⊘ Search Console link already exists.{NC}")
        else:
            print(f"  {YELLOW}⚠ Could not link Search Console to GA4: {e}{NC}")
            print(f"  {YELLOW}  → Link manually: GA4 → Admin → Product Links → Search Console{NC}")


# ─── Google Tag Manager ─────────────────────────────────────────────────

def setup_gtm(creds, ga4_measurement_id: str, *, domain: str, step_label: str = "") -> str:
    """Create GTM account + container with GA4 tag. Returns container_public_id (GTM-XXXXX)."""
    separator(step_label or "Google Tag Manager")

    service = build("tagmanager", "v2", credentials=creds)

    # Check existing accounts
    try:
        accounts_response = service.accounts().list().execute()
        accounts = accounts_response.get("account", [])
    except Exception as exc:
        if is_google_api_disabled_error(exc):
            print(f"  {YELLOW}⊘ Tag Manager API is not enabled for this OAuth project.{NC}")
            print_google_api_enable_hint("tagmanager.googleapis.com", creds)
            print(f"  {YELLOW}  GTM setup skipped for now. Re-run the script after enabling it.{NC}")
            return ""
        raise

    container = None
    account_path = None

    # Look for existing container
    for acc in accounts:
        containers_response = service.accounts().containers().list(parent=acc["path"]).execute()
        for c in containers_response.get("container", []):
            if domain in (c.get("name", "") + " " + " ".join(c.get("domainName", []))):
                container = c
                account_path = acc["path"]
                print(f"  {YELLOW}⊘ Container already exists:{NC} {c.get('name')} ({c['publicId']})")
                break
        if container:
            break

    if not container:
        # Create account + container
        if accounts:
            account_path = accounts[0]["path"]
            print(f"  Using GTM account: {CYAN}{accounts[0].get('name', account_path)}{NC}")
        else:
            print(f"  {RED}✗ No GTM accounts found. Creating the first GTM account is not supported here.{NC}")
            print(f"  {YELLOW}  → Go to https://tagmanager.google.com and create your first GTM account manually.{NC}")
            print(f"  {YELLOW}  → Then re-run this script to create or reuse the web container.{NC}")
            return ""

        container_body = {
            "name": domain,
            "usageContext": ["web"],
            "domainName": [domain],
        }
        container = (
            service.accounts()
            .containers()
            .create(parent=account_path, body=container_body)
            .execute()
        )
        print(f"  {GREEN}✓ Created GTM container:{NC} {container.get('name')} ({container['publicId']})")

    gtm_id = container["publicId"]
    container_path = container["path"]

    # Create workspace, GA4 tag, and publish
    if ga4_measurement_id:
        try:
            # Create a workspace for our changes
            ws = (
                service.accounts()
                .containers()
                .workspaces()
                .create(parent=container_path, body={"name": "Analytics Setup"})
                .execute()
            )
            ws_path = ws["path"]

            # Create "All Pages" trigger (built-in, but we need to reference it)
            # Trigger ID 2147479553 is the built-in "All Pages" trigger
            ALL_PAGES_TRIGGER_ID = "2147479553"

            # Create GA4 Configuration tag
            ga4_tag_body = {
                "name": "GA4 Configuration",
                "type": "gaawc",
                "parameter": [
                    {"type": "template", "key": "measurementId", "value": ga4_measurement_id},
                    {"type": "boolean", "key": "sendPageView", "value": "true"},
                ],
                "firingTriggerId": [ALL_PAGES_TRIGGER_ID],
                "consentSettings": {
                    "consentStatus": "needed",
                    "consentType": {"type": "list", "list": [
                        {"type": "template", "value": "analytics_storage"},
                    ]},
                },
            }
            tag = (
                service.accounts()
                .containers()
                .workspaces()
                .tags()
                .create(parent=ws_path, body=ga4_tag_body)
                .execute()
            )
            print(f"  {GREEN}✓ Created GA4 tag:{NC} {tag.get('name')} (Measurement ID: {ga4_measurement_id})")

            # Create version and publish
            version = (
                service.accounts()
                .containers()
                .workspaces()
                .create_version(parent=ws_path, body={"name": "Initial Analytics Setup"})
                .execute()
            )
            version_path = version.get("containerVersion", {}).get("path")
            if version_path:
                service.accounts().containers().versions().publish(path=version_path).execute()
                print(f"  {GREEN}✓ Published GTM container with GA4 tag.{NC}")
        except Exception as e:
            print(f"  {YELLOW}⚠ Could not auto-create GA4 tag in GTM: {e}{NC}")
            print(f"  {YELLOW}  → Manually create a GA4 Configuration tag in GTM with ID: {ga4_measurement_id}{NC}")

    return gtm_id


# ─── Google Search Console ──────────────────────────────────────────────

def setup_search_console(creds, *, domain: str, site_url: str, step_label: str = "") -> str:
    """Add site to Search Console and get verification meta tag. Returns verification code."""
    separator(step_label or "Google Search Console")

    webmasters_service = build("webmasters", "v3", credentials=creds)

    # Check if site already exists
    try:
        sites_response = webmasters_service.sites().list().execute()
        existing = [s for s in sites_response.get("siteEntry", []) if domain in s.get("siteUrl", "")]
        if existing:
            print(f"  {YELLOW}⊘ Site already in Search Console:{NC} {existing[0]['siteUrl']}")
    except Exception:
        pass

    # Add the site (idempotent)
    try:
        webmasters_service.sites().add(siteUrl=site_url).execute()
        print(f"  {GREEN}✓ Added site:{NC} {site_url}")
    except Exception as e:
        if "already been verified" in str(e).lower() or "already exists" in str(e).lower():
            print(f"  {YELLOW}⊘ Site already verified.{NC}")
        else:
            print(f"  {GREEN}✓ Site add request sent:{NC} {site_url}")

    # Get verification token via Site Verification API
    verification_code = ""
    try:
        verify_service = build("siteVerification", "v1", credentials=creds)
        token_response = verify_service.webResource().getToken(body={
            "site": {"type": "SITE", "identifier": site_url},
            "verificationMethod": "META",
        }).execute()
        verification_code = token_response.get("token", "")
        # Extract just the content value from the meta tag
        match = re.search(r'content="([^"]+)"', verification_code)
        if match:
            verification_code = match.group(1)
        print(f"  {GREEN}✓ Verification meta tag:{NC} {verification_code}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not get verification token: {e}{NC}")
        print(f"  {YELLOW}  → Get it manually from Search Console → Settings → Ownership verification{NC}")

    # Submit sitemap
    try:
        webmasters_service.sitemaps().submit(siteUrl=site_url, feedpath=f"{site_url}/sitemap.xml").execute()
        print(f"  {GREEN}✓ Submitted sitemap:{NC} {site_url}/sitemap.xml")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not submit sitemap (do it after deploy): {e}{NC}")

    return verification_code


# ─── Bing Webmaster Tools ───────────────────────────────────────────────

def setup_bing(
    bing_api_key: str,
    bing_client_id: str,
    _bing_client_secret: str,
    _bing_tenant_id: str,
    *,
    domain: str,
    site_url: str,
    step_label: str = "",
) -> str:
    """Add site to Bing Webmaster Tools via API key. Returns verification meta tag content."""
    separator(step_label or "Bing Webmaster Tools")

    if not bing_api_key:
        if bing_client_id:
            print(f"  {YELLOW}⚠ Bing OAuth app credentials detected, but this script no longer uses them for Webmaster provisioning.{NC}")
            print(f"  {YELLOW}  → `BING_CLIENT_ID` / `BING_CLIENT_SECRET` still remain valid for Microsoft user SSO.{NC}")
        print(f"  {YELLOW}⊘ BING_WEBMASTER_API_KEY not set. Skipping automated Bing provisioning.{NC}")
        print(f"  {YELLOW}  → Add the site manually at https://www.bing.com/webmasters or provide a Bing Webmaster API key.{NC}")
        return ""

    print(f"  {GREEN}✓ Using Bing Webmaster API key provisioning.{NC}")

    headers = {"Content-Type": "application/json"}
    api_key_param = f"apikey={bing_api_key}"

    # Get existing sites
    try:
        resp = requests.get(f"{BING_WEBMASTER_API}/GetUserSites?{api_key_param}", headers=headers, timeout=30)
        if resp.ok:
            sites = resp.json().get("d", [])
            for site in sites:
                if domain in site.get("Url", ""):
                    print(f"  {YELLOW}⊘ Site already in Bing Webmaster Tools.{NC}")
                    # Try to get verification meta tag
                    break
    except Exception:
        pass

    # Add site
    try:
        add_payload = json.dumps({"siteUrl": site_url})
        resp = requests.post(
            f"{BING_WEBMASTER_API}/AddSite?{api_key_param}",
            data=add_payload,
            headers=headers,
            timeout=30,
        )
        if resp.ok or resp.status_code == 400:  # 400 = already exists
            print(f"  {GREEN}✓ Site add request sent to Bing.{NC}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not add site to Bing: {e}{NC}")

    # Get verification meta tag
    bing_verification = ""
    try:
        verify_resp = requests.get(
            f"{BING_WEBMASTER_API}/GetVerificationCode?{api_key_param}&siteUrl={site_url}",
            headers=headers,
            timeout=30,
        )
        if verify_resp.ok:
            raw = verify_resp.json().get("d", "")
            # Extract just the content value
            match = re.search(r'content="([^"]+)"', raw)
            bing_verification = match.group(1) if match else raw
            if bing_verification:
                print(f"  {GREEN}✓ Bing verification code:{NC} {bing_verification}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not get Bing verification code: {e}{NC}")

    if not bing_verification:
        print(f"  {YELLOW}  → Get verification code manually from https://www.bing.com/webmasters{NC}")

    # Submit sitemap to Bing
    try:
        sitemap_payload = json.dumps({
            "siteUrl": site_url,
            "feedUrl": f"{site_url}/sitemap.xml",
        })
        resp = requests.post(
            f"{BING_WEBMASTER_API}/SubmitSitemap?{api_key_param}",
            data=sitemap_payload,
            headers=headers,
            timeout=30,
        )
        if resp.ok:
            print(f"  {GREEN}✓ Submitted sitemap to Bing:{NC} {site_url}/sitemap.xml")
    except Exception:
        pass

    # Submit key pages for URL indexing
    key_pages = ["/", "/pricing", "/docs", "/blog", "/about", "/faq"]
    try:
        url_list = [f"{site_url}{page}" for page in key_pages]
        resp = requests.post(
            f"{BING_WEBMASTER_API}/SubmitUrlbatch?{api_key_param}",
            data=json.dumps({"siteUrl": site_url, "urlList": url_list}),
            headers=headers,
            timeout=30,
        )
        if resp.ok:
            print(f"  {GREEN}✓ Submitted {len(url_list)} key URLs to Bing for indexing.{NC}")
        else:
            # Fall back to individual submissions
            submitted = 0
            for page_url in url_list:
                try:
                    r = requests.post(
                        f"{BING_WEBMASTER_API}/SubmitUrl?{api_key_param}",
                        data=json.dumps({"siteUrl": site_url, "url": page_url}),
                        headers=headers,
                        timeout=15,
                    )
                    if r.ok:
                        submitted += 1
                except Exception:
                    pass
            if submitted:
                print(f"  {GREEN}✓ Submitted {submitted}/{len(url_list)} URLs to Bing individually.{NC}")
    except Exception as e:
        print(f"  {YELLOW}⚠ Could not submit URLs to Bing: {e}{NC}")

    return bing_verification


# ─── GTM Container Config Instructions ──────────────────────────────────

def print_gtm_manual_steps(gtm_id: str, ga4_measurement_id: str) -> None:
    """Print manual GTM tag setup steps if auto-creation failed."""
    separator("GTM Container Consent Mode Setup")
    print(textwrap.dedent(f"""\
    If the GA4 tag was auto-created, you still need to configure Consent Mode v2:

    1. Open GTM → Container {CYAN}{gtm_id}{NC}
    2. Admin → Container Settings → {BOLD}Enable Consent Overview{NC}
    3. For the GA4 Configuration tag:
       - Click → Advanced Settings → Consent Settings
       - Set "Require additional consent": {BOLD}analytics_storage{NC}
    4. Default consent state should be: {BOLD}denied{NC}
       (The app pushes 'consent_update' dataLayer events when user grants consent)
    5. Click {BOLD}Submit → Publish{NC} the container.
    """))


# ─── Post-deploy checklist ──────────────────────────────────────────────

def print_checklist(site_url: str, *, skip_rebuild: bool = False) -> None:
    separator("Post-Deploy Verification Checklist")
    rebuild_line = f"  {GREEN}✓ Rebuild:            done{NC}" if skip_rebuild else "  □ Rebuild:            docker compose up --build frontend"
    print(f"""\
  After deploying with the new env vars:

{rebuild_line}
  □ Verify sitemap:     curl {site_url}/sitemap.xml
  □ Verify robots.txt:  curl {site_url}/robots.txt
  □ Google Search Console → click 'Verify' (or it auto-verifies via meta tag)
  □ Bing Webmaster Tools → click 'Verify' (or it auto-verifies via meta tag)
  □ GTM Preview mode → verify GA4 tag fires on page load
  □ GA4 Real-Time → verify page_view events appear
  □ GA4 Admin → Data Settings → Data Retention → verify 14 months
  □ GA4 Admin → Data Streams → Enhanced Measurement → verify all toggles on
  □ GA4 Admin → Events → Key Events → verify sign_up, login, purchase etc.
  □ GA4 Admin → Custom Definitions → verify user_plan, audit_type etc.
  □ GA4 Admin → Product Links → Search Console → verify linked
  □ Cookie consent test: reject → NO GA4 events; accept → events resume
    """)


# ─── Interactive helpers ─────────────────────────────────────────────────

def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no. Returns bool. Non-interactive stdin defaults."""
    hint = "[Y/n]" if default else "[y/N]"
    if not sys.stdin.isatty():
        return default
    try:
        answer = input(f"  {question} {hint} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def prompt_input(label: str, *, secret: bool = False) -> str:
    """Prompt user for a text value. Returns stripped string."""
    if not sys.stdin.isatty():
        return ""
    try:
        if secret:
            import getpass
            return getpass.getpass(f"  {label}: ").strip()
        return input(f"  {label}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def detect_ssh_session() -> bool:
    """Return True if we appear to be running inside an SSH session."""
    return bool(os.getenv("SSH_CONNECTION") or os.getenv("SSH_TTY") or os.getenv("SSH_CLIENT"))


def check_port_available(port: int) -> bool:
    """Return True if the given TCP port is free on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def detect_compose_file() -> str:
    """Find the right docker compose file. VPS uses docker-compose.vps.yml."""
    vps_compose = PROJECT_ROOT / "docker-compose.vps.yml"
    dev_compose = PROJECT_ROOT / "docker-compose.yml"
    if vps_compose.exists():
        return str(vps_compose)
    if dev_compose.exists():
        return str(dev_compose)
    return "docker-compose.yml"


def check_docker_available() -> bool:
    """Check if docker compose is available."""
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def rebuild_frontend(compose_file: str) -> bool:
    """Rebuild and restart only the frontend container. Returns True on success."""
    separator("Rebuilding Frontend Container")
    print(f"  Compose file: {CYAN}{compose_file}{NC}")
    print(f"  {YELLOW}▸ Rebuilding frontend (NEXT_PUBLIC_ vars require a full rebuild)...{NC}\n")

    try:
        result = subprocess.run(
            [
                "docker", "compose", "-f", compose_file,
                "up", "-d", "--no-deps", "--build", "frontend",
            ],
            cwd=str(PROJECT_ROOT),
            timeout=600,
        )
        if result.returncode == 0:
            print(f"\n  {GREEN}✓ Frontend container rebuilt and restarted.{NC}")
            return True
        else:
            print(f"\n  {RED}✗ Frontend rebuild exited with code {result.returncode}.{NC}")
            print(f"  {YELLOW}  → Check logs: docker compose -f {compose_file} logs frontend{NC}")
            return False
    except subprocess.TimeoutExpired:
        print(f"\n  {RED}✗ Frontend rebuild timed out (10 min).{NC}")
        return False
    except Exception as e:
        print(f"\n  {RED}✗ Failed to rebuild frontend: {e}{NC}")
        return False


def health_check_frontend(compose_file: str, site_url: str) -> None:
    """Quick health check on the frontend after rebuild."""
    print(f"\n  {YELLOW}▸ Waiting for frontend to become healthy...{NC}")
    import time
    for attempt in range(1, 13):
        time.sleep(5)
        try:
            result = subprocess.run(
                [
                    "docker", "compose", "-f", compose_file,
                    "exec", "-T", "frontend",
                    "wget", "-q", "--spider", "http://localhost:3000",
                ],
                capture_output=True, timeout=10,
                cwd=str(PROJECT_ROOT),
            )
            if result.returncode == 0:
                print(f"  {GREEN}✓ Frontend is healthy (attempt {attempt}/12).{NC}")
                return
        except Exception:
            pass
        if attempt < 12:
            sys.stdout.write(f"\r  Attempt {attempt}/12...")
            sys.stdout.flush()

    print(f"\n  {YELLOW}⚠ Frontend health check inconclusive after 60s.{NC}")
    print(f"  {YELLOW}  → Verify manually: curl -sI {site_url}{NC}")


# ─── Pre-flight checks ──────────────────────────────────────────────────

def preflight_checks(args: argparse.Namespace, env: dict) -> dict:
    """
    Run all pre-flight checks and return a config dict with:
      headless, port, google_client_id, google_client_secret,
      bing_api_key, bing_client_id, bing_client_secret, bing_tenant_id,
      run_ga4, run_gtm, run_gsc, run_bing, run_rebuild, compose_file
    """
    separator("Pre-flight Checks")
    config: dict = {}

    # ── 1. Detect environment ──────────────────────────────────────────
    is_ssh = detect_ssh_session()
    headless = args.headless or is_ssh
    config["headless"] = headless
    config["port"] = args.google_port

    if is_ssh and not args.headless:
        print(f"  {GREEN}✓{NC} SSH session detected — enabling headless OAuth automatically.")
    elif headless:
        print(f"  {GREEN}✓{NC} Headless mode: enabled (--headless flag).")
    else:
        print(f"  {GREEN}✓{NC} Local environment detected — will open browser for OAuth.")

    # ── 2. Check Google OAuth credentials ──────────────────────────────
    google_client_id = get_env("GOOGLE_CLIENT_ID", env)
    google_client_secret = get_env("GOOGLE_CLIENT_SECRET", env)

    if google_client_id and google_client_secret:
        print(f"  {GREEN}✓{NC} GOOGLE_CLIENT_ID: {CYAN}{google_client_id[:24]}...{NC}")
        print(f"  {GREEN}✓{NC} GOOGLE_CLIENT_SECRET: ****{google_client_secret[-4:]}")
    else:
        print(f"  {RED}✗{NC} GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET missing.")
        if not args.yes:
            print(f"\n  {YELLOW}These credentials come from Google Cloud Console → APIs & Services → Credentials.{NC}")
            google_client_id = google_client_id or prompt_input("Enter GOOGLE_CLIENT_ID")
            google_client_secret = google_client_secret or prompt_input("Enter GOOGLE_CLIENT_SECRET", secret=True)
        if not google_client_id or not google_client_secret:
            print(f"  {RED}✗ Cannot proceed without Google OAuth credentials.{NC}")
            sys.exit(1)
        print(f"  {GREEN}✓{NC} Google credentials provided interactively.")

    config["google_client_id"] = google_client_id
    config["google_client_secret"] = google_client_secret

    # ── 3. Check Bing credentials (optional) ───────────────────────────
    bing_api_key = get_env("BING_WEBMASTER_API_KEY", env)
    bing_client_id = get_env("BING_CLIENT_ID", env)
    bing_client_secret = get_env("BING_CLIENT_SECRET", env)
    bing_tenant_id = get_env("BING_TENANT_ID", env) or "common"

    if bing_api_key:
        print(f"  {GREEN}✓{NC} BING_WEBMASTER_API_KEY: ****{bing_api_key[-4:]}")
    else:
        print(f"  {YELLOW}⊘{NC} BING_WEBMASTER_API_KEY not set (Bing setup will show manual instructions).")

    config["bing_api_key"] = bing_api_key
    config["bing_client_id"] = bing_client_id
    config["bing_client_secret"] = bing_client_secret
    config["bing_tenant_id"] = bing_tenant_id

    # ── 4. Check OAuth callback port ───────────────────────────────────
    port = args.google_port
    if check_port_available(port):
        print(f"  {GREEN}✓{NC} OAuth callback port {port} is available.")
    else:
        print(f"  {RED}✗{NC} Port {port} is already in use.")
        if not args.yes:
            alt = prompt_input(f"Enter an alternative port (or press Enter to try {port} anyway)")
            if alt.isdigit():
                port = int(alt)
                config["port"] = port
        if not check_port_available(port):
            print(f"  {YELLOW}⚠{NC} Port {port} is busy — OAuth callback may fail. Proceeding anyway.")

    # ── 5. Docker / compose availability ───────────────────────────────
    has_docker = check_docker_available()
    compose_file = detect_compose_file()
    config["compose_file"] = compose_file
    if has_docker:
        print(f"  {GREEN}✓{NC} Docker Compose available. Compose file: {CYAN}{compose_file}{NC}")
    else:
        print(f"  {YELLOW}⊘{NC} Docker Compose not found — automatic rebuild will be skipped.")

    config["has_docker"] = has_docker

    # ── 6. SSH tunnel reminder for headless ────────────────────────────
    if headless:
        print(f"\n  {YELLOW}{'─' * 58}{NC}")
        print(f"  {BOLD}SSH Tunnel Required for OAuth Callback{NC}")
        print(f"  {YELLOW}{'─' * 58}{NC}")
        print(f"  Open a {BOLD}second terminal{NC} on your local machine and run:")
        print(f"  {BOLD}  ssh -L {port}:127.0.0.1:{port} <user>@<your-vps-ip>{NC}")
        print("\n  The script will print a Google consent URL.")
        print("  Open it in your local browser. After authorizing,")
        print("  the callback flows through the tunnel back here.")
        print(f"  {YELLOW}{'─' * 58}{NC}")
        if not args.yes:
            if not prompt_yes_no("SSH tunnel ready? Continue?"):
                print(f"\n  {YELLOW}Aborted. Set up the tunnel and re-run.{NC}")
                sys.exit(0)

    # ── 7. Service selection ───────────────────────────────────────────
    if args.yes:
        config["run_ga4"] = True
        config["run_gtm"] = True
        config["run_gsc"] = True
        config["run_bing"] = True
        config["run_rebuild"] = not args.skip_rebuild and has_docker
    else:
        print(f"\n  {BOLD}Select which services to provision:{NC}")
        config["run_ga4"] = prompt_yes_no("Set up Google Analytics 4 (GA4)?")
        config["run_gtm"] = prompt_yes_no("Set up Google Tag Manager (GTM)?")
        config["run_gsc"] = prompt_yes_no("Set up Google Search Console?")
        config["run_bing"] = prompt_yes_no("Set up Bing Webmaster Tools?")
        if not args.skip_rebuild and has_docker:
            config["run_rebuild"] = prompt_yes_no("Rebuild frontend container after writing env vars?")
        else:
            config["run_rebuild"] = False

    # Validate at least one Google service selected (need OAuth)
    needs_google_oauth = config["run_ga4"] or config["run_gtm"] or config["run_gsc"]
    config["needs_google_oauth"] = needs_google_oauth

    if not any([config["run_ga4"], config["run_gtm"], config["run_gsc"], config["run_bing"]]):
        print(f"\n  {YELLOW}No services selected. Nothing to do.{NC}")
        sys.exit(0)

    # ── Summary ────────────────────────────────────────────────────────
    selected = []
    if config["run_ga4"]:
        selected.append("GA4")
    if config["run_gtm"]:
        selected.append("GTM")
    if config["run_gsc"]:
        selected.append("Search Console")
    if config["run_bing"]:
        selected.append("Bing")
    print(f"\n  {GREEN}▸ Services to provision:{NC} {', '.join(selected)}")
    if config["run_rebuild"]:
        print(f"  {GREEN}▸ Frontend rebuild:{NC} yes")
    print()

    return config


# ─── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    domain, site_url, write_targets = resolve_runtime_targets(args)
    banner(domain, write_targets)

    env = load_env_files()

    # ── Pre-flight ─────────────────────────────────────────────────────
    config = preflight_checks(args, env)

    # ── Google OAuth (only if needed) ──────────────────────────────────
    creds = None
    if config["needs_google_oauth"]:
        separator("Google OAuth Sign-In")
        print("  Requesting scopes: GA4 Admin, Tag Manager, Search Console")
        print(f"  Client ID: {CYAN}{config['google_client_id'][:24]}...{NC}\n")
        creds = google_oauth_flow(
            config["google_client_id"],
            config["google_client_secret"],
            headless=config["headless"],
            port=config["port"],
        )

    # ── Run selected services ──────────────────────────────────────────
    ga4_property_id = ""
    ga4_measurement_id = ""
    gtm_id = ""
    google_verification = ""
    bing_verification = ""

    # Build step labels dynamically
    enabled = []
    if config["run_ga4"]:
        enabled.append("GA4")
    if config["run_gtm"]:
        enabled.append("GTM")
    if config["run_gsc"]:
        enabled.append("Search Console")
    if config["run_bing"]:
        enabled.append("Bing")
    total = len(enabled)

    step = 0

    if config["run_ga4"]:
        step += 1
        label = f"Step {step} / {total} — Google Analytics 4"
        ga4_property_id, ga4_measurement_id = setup_ga4(
            creds, domain=domain, site_url=site_url, step_label=label,
        )

    if config["run_gtm"]:
        step += 1
        label = f"Step {step} / {total} — Google Tag Manager"
        gtm_id = setup_gtm(
            creds, ga4_measurement_id, domain=domain, step_label=label,
        )

    if config["run_gsc"]:
        step += 1
        label = f"Step {step} / {total} — Google Search Console"
        google_verification = setup_search_console(
            creds, domain=domain, site_url=site_url, step_label=label,
        )

    if config["run_bing"]:
        step += 1
        label = f"Step {step} / {total} — Bing Webmaster Tools"
        bing_verification = setup_bing(
            config["bing_api_key"],
            config["bing_client_id"],
            config["bing_client_secret"],
            config["bing_tenant_id"],
            domain=domain,
            site_url=site_url,
            step_label=label,
        )

    # ── Write env vars ─────────────────────────────────────────────────
    separator("Writing Environment Variables")
    updates: dict[str, str] = {}
    if config["run_ga4"]:
        updates["NEXT_PUBLIC_GA4_MEASUREMENT_ID"] = ga4_measurement_id
    if config["run_gtm"]:
        updates["NEXT_PUBLIC_GTM_ID"] = gtm_id
    if config["run_gsc"]:
        updates["NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION"] = google_verification
    if config["run_bing"]:
        updates["NEXT_PUBLIC_BING_SITE_VERIFICATION"] = bing_verification

    if any(updates.values()):
        update_env_files(write_targets, updates)
    else:
        print(f"  {YELLOW}⊘ No new values to write.{NC}")

    # ── GTM manual steps ───────────────────────────────────────────────
    if gtm_id and ga4_measurement_id:
        print_gtm_manual_steps(gtm_id, ga4_measurement_id)

    # ── Rebuild frontend ───────────────────────────────────────────────
    rebuild_ok = False
    if config["run_rebuild"] and any(updates.values()):
        rebuild_ok = rebuild_frontend(config["compose_file"])
        if rebuild_ok:
            health_check_frontend(config["compose_file"], site_url)
    elif config["run_rebuild"]:
        print(f"\n  {YELLOW}⊘ No env vars changed — skipping rebuild.{NC}")
    else:
        if any(updates.values()):
            print(f"\n  {YELLOW}▸ Env vars written. Remember to rebuild the frontend:{NC}")
            print(f"    docker compose -f {config['compose_file']} up -d --no-deps --build frontend")

    # ── Post-deploy checklist ──────────────────────────────────────────
    print_checklist(site_url, skip_rebuild=rebuild_ok)

    # ── Summary ────────────────────────────────────────────────────────
    separator("Summary")
    if config["run_ga4"]:
        print(f"  GA4 Property ID:      {GREEN}{ga4_property_id or '(not obtained)'}{NC}")
        print(f"  GA4 Measurement ID:   {GREEN}{ga4_measurement_id or '(not obtained)'}{NC}")
    if config["run_gtm"]:
        print(f"  GTM Container ID:     {GREEN}{gtm_id or '(not obtained)'}{NC}")
    if config["run_gsc"]:
        print(f"  Google Verification:  {GREEN}{google_verification or '(not obtained)'}{NC}")
    if config["run_bing"]:
        print(f"  Bing Verification:    {GREEN}{bing_verification or '(not obtained)'}{NC}")
    if rebuild_ok:
        print(f"  Frontend Rebuild:     {GREEN}done{NC}")
    print(f"\n  {GREEN}{BOLD}✓ Setup complete!{NC}\n")


if __name__ == "__main__":
    main()
