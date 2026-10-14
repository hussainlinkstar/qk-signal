import hashlib


def build_audit_cache_key(
    url: str, provider: str, tier: str, context_fingerprint: str | None = None
) -> str:
    context_part = context_fingerprint if context_fingerprint is not None else "<none>"
    raw_key = f"{url}|{provider}|{tier}|{context_part}"
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"audit:cache:{hashed_key}"
