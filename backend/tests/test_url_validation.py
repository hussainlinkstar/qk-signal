import sys
from pathlib import Path
import socket

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from services.url_validation import normalize_and_validate_url


@pytest.mark.parametrize(
    "raw_url",
    [
        "http://127.0.0.1",
        "http://169.254.10.20",
        "http://10.0.0.5",
        "http://172.16.0.10",
        "http://192.168.1.2",
        "http://localhost:8000",
        "example.com",
        "htp://bad",
        "https://exa mple.com",
        "ftp://example.com",
        "http://",
        "not a url",
    ],
)
def test_normalize_and_validate_url_blocks_unsafe_targets(raw_url: str):
    with pytest.raises(ValueError):
        normalize_and_validate_url(raw_url)


def test_normalize_and_validate_url_allows_public_domain_with_http_scheme():
    assert (
        normalize_and_validate_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
    )


def test_normalize_and_validate_url_honors_allowlist(monkeypatch):
    monkeypatch.setenv("URL_VALIDATION_ALLOWLIST", "example.com")
    assert normalize_and_validate_url("https://www.example.com") == "https://www.example.com"

    with pytest.raises(ValueError, match="allowlist"):
        normalize_and_validate_url("https://openai.com")


def test_normalize_and_validate_url_honors_denylist(monkeypatch):
    monkeypatch.setenv("URL_VALIDATION_DENYLIST", "*.example.com")
    with pytest.raises(ValueError, match="denylist"):
        normalize_and_validate_url("https://api.example.com")


def test_normalize_and_validate_url_blocks_hostnames_resolving_to_private_ips(monkeypatch):
    def fake_getaddrinfo(host, port, type):
        _ = host, port, type
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="Private or reserved"):
        normalize_and_validate_url("https://public-looking.example")


def test_normalize_and_validate_url_allows_unresolved_domains(monkeypatch):
    def fake_getaddrinfo(host, port, type):
        _ = host, port, type
        raise OSError("dns lookup failed")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert (
        normalize_and_validate_url("https://not-yet-provisioned.example")
        == "https://not-yet-provisioned.example"
    )
