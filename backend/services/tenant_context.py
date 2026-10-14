from __future__ import annotations

from contextvars import ContextVar, Token

_tenant_workspace_id_ctx: ContextVar[int | None] = ContextVar("tenant_workspace_id", default=None)
_tenant_domain_ctx: ContextVar[str | None] = ContextVar("tenant_domain", default=None)
_active_workspace_id_ctx: ContextVar[int | None] = ContextVar("active_workspace_id", default=None)


def set_tenant_workspace_id(workspace_id: int | None) -> Token:
    return _tenant_workspace_id_ctx.set(workspace_id)


def reset_tenant_workspace_id(token: Token) -> None:
    _tenant_workspace_id_ctx.reset(token)


def get_tenant_workspace_id() -> int | None:
    return _tenant_workspace_id_ctx.get()


def set_tenant_domain(domain: str | None) -> Token:
    return _tenant_domain_ctx.set(domain)


def reset_tenant_domain(token: Token) -> None:
    _tenant_domain_ctx.reset(token)


def get_tenant_domain() -> str | None:
    return _tenant_domain_ctx.get()


def set_active_workspace_id(workspace_id: int | None) -> Token:
    return _active_workspace_id_ctx.set(workspace_id)


def reset_active_workspace_id(token: Token) -> None:
    _active_workspace_id_ctx.reset(token)


def get_active_workspace_id() -> int | None:
    return _active_workspace_id_ctx.get()
