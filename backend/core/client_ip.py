"""Trusted-proxy-aware client IP resolution (SIGV2-1243).

Identity headers are only honored when the immediate TCP peer is a trusted
proxy, per ``settings.TRUSTED_PROXY_CIDRS``. ``x-forwarded-for`` is then walked
RIGHT to LEFT, skipping hops that are themselves trusted proxies, and the
first untrusted entry wins: on an appending edge that is the client IP, and
client-injected entries further left can never be positioned after the real
one.

``cf-connecting-ip`` and ``x-real-ip`` are deliberately not consulted. Verified
empirically against preprod on 2026-10-09: a forged ``cf-connecting-ip``
survived the whole Traefik -> Caddy -> BFF chain and was used as the resolved
IP, so these headers are attacker-controlled unless the deployment's edge is
known to overwrite them (Cloudflare does for ``cf-connecting-ip`` when it
fronts the site, but nothing in the request itself proves it did). The XFF
chain already carries the real client in both cases.

Default ``TRUSTED_PROXY_CIDRS`` covers loopback, RFC1918 space (the Docker
Traefik/Caddy/BFF hops) and the published Cloudflare ranges used in
deploy/Caddyfile, so a Cloudflare-fronted deployment resolves the real client
instead of collapsing onto the CF edge IP.
"""

import ipaddress
import logging
from functools import lru_cache

from fastapi import Request

from core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def _parse_trusted_networks(raw_cidrs: str) -> tuple:
    networks = []
    for item in raw_cidrs.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted proxy CIDR %r", item)
    return tuple(networks)


def _is_trusted_proxy(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        address in network
        for network in _parse_trusted_networks(settings.TRUSTED_PROXY_CIDRS or "")
    )


def resolve_client_ip(request: Request) -> str:
    """Return the client IP, trusting ``x-forwarded-for`` only from known proxies.

    The header is walked right-to-left: the leftmost entries are the only ones
    a client could inject past an appending edge, so they are skipped until the
    first untrusted hop.
    """
    peer = request.client.host if request.client else None
    if peer and _is_trusted_proxy(peer):
        forwarded = request.headers.get("x-forwarded-for", "")
        entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
        for candidate in reversed(entries):
            if not _is_trusted_proxy(candidate):
                return candidate
        # Every entry is trusted: the chain only named proxies.
        return peer
    return peer or "unknown"
