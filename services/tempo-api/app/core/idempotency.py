"""Idempotency-Key handling — §8.1, INT-006.

"Idempotency-Key required for run creation and actions; same key + same body
returns same result." Keyed by (tenant_id, endpoint, key) so two tenants or
two endpoints can't collide on the same client-chosen key.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any


def hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class IdempotentRecord:
    payload_hash: str
    response: dict[str, Any]


class IdempotencyConflict(Exception):
    """Same key reused with a different request body."""


class IdempotencyStore:
    """In-process store for Phase 0. Swap for a shared table/cache before
    running more than one API replica (see docs/roadmap.md, Phase F).
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], IdempotentRecord] = {}
        self._lock = threading.Lock()

    def get_or_reserve(
        self, tenant_id: str, endpoint: str, key: str, payload: dict[str, Any]
    ) -> IdempotentRecord | None:
        """Returns the existing record if this exact (key, payload) was seen
        before, or None if this is a new request that the caller should now
        process (and later store via `store`).
        """
        payload_hash = hash_payload(payload)
        with self._lock:
            existing = self._records.get((tenant_id, endpoint, key))
            if existing is None:
                return None
            if existing.payload_hash != payload_hash:
                raise IdempotencyConflict(
                    f"idempotency key '{key}' was already used with a different request body"
                )
            return existing

    def store(self, tenant_id: str, endpoint: str, key: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
        payload_hash = hash_payload(payload)
        with self._lock:
            self._records[(tenant_id, endpoint, key)] = IdempotentRecord(payload_hash=payload_hash, response=response)


idempotency_store = IdempotencyStore()
