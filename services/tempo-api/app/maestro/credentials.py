"""Connector credential storage — INT-03: "Store encrypted connector
credentials in OCI Vault and retain only secret references in application
data." No OCI Vault exists in this environment (ADR-0002's Oracle/OCI
topology isn't approved, and there's no OCI account reachable from here
regardless). `InMemoryCredentialStore` is the same class of disclosed,
dev-only stand-in as `app.maestro.writeback.NotImplementedWritebackClient`:
it exists so the surrounding lifecycle (store -> test -> activate ->
suspend/revoke) is real and testable now, without pretending a live Vault
integration exists.

Concretely: secrets live in this process's memory only (never written to
disk or the database — `app.models.connectors.ConnectorCredentialReference`
persists only the opaque reference this store returns, never the secret
itself, matching `MaestroConnection`'s own long-standing docstring
promise). Losing them on process restart is correct behaviour for
something never meant to hold a real secret, not a bug to fix here.

`test()` cannot validate anything against a real vendor endpoint — no
vendor sandbox credentials exist either (Phase 3's own INT-05/INT-06 are
blocked for the same underlying reason). It honestly reports only what it
can check (the reference exists in the store), never a fabricated live
handshake — the same "never fabricate confirmed" posture
`NotImplementedWritebackClient` takes for writeback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


class CredentialNotFound(Exception):
    pass


@dataclass(frozen=True)
class CredentialTestResult:
    ok: bool
    detail: str


class CredentialStore(Protocol):
    def store(self, connection_id: str, secret: dict[str, Any]) -> str:
        """Returns an opaque reference — never the secret itself."""
        ...

    def test(self, reference: str) -> CredentialTestResult: ...

    def revoke(self, reference: str) -> None:
        """Best-effort — revoking an already-unknown reference is a no-op,
        the same "safe to call twice" convention app/api/v1/actions.py's
        reconcile endpoint already uses.
        """
        ...


class InMemoryCredentialStore:
    """The dev-only stand-in — see module docstring."""

    def __init__(self) -> None:
        self._secrets: dict[str, dict[str, Any]] = {}

    def store(self, connection_id: str, secret: dict[str, Any]) -> str:
        reference = f"cred_{uuid.uuid4().hex[:20]}"
        self._secrets[reference] = secret
        return reference

    def test(self, reference: str) -> CredentialTestResult:
        if reference not in self._secrets:
            return CredentialTestResult(ok=False, detail="credential reference not found")
        return CredentialTestResult(
            ok=True,
            detail="credential reference present in store — no live vendor endpoint was contacted or verified",
        )

    def revoke(self, reference: str) -> None:
        self._secrets.pop(reference, None)


# Module-level, matching app.maestro.writeback's `writeback_client` /
# app.core.idempotency's `idempotency_store` convention (no DI container
# in this codebase) — tests substitute a fake by monkeypatching this name
# directly, the same way those do.
credential_store: CredentialStore = InMemoryCredentialStore()
