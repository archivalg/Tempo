"""Action tokens — Integration Spec §12.2's "expiring action_token".

HMAC-signed opaque tokens, not JWT (no new dependency for a token whose
only consumer is this same service — there's no third party that needs to
independently verify it). Encodes action_id + payload_hash + expiry so a
token can't be replayed against a different action or a payload that
changed since validation. Signed with `settings.action_token_secret` — see
its docstring for why the default must not reach production.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from app.config import settings


class ActionTokenInvalid(Exception):
    """Token is malformed, mis-signed, doesn't match this action/payload, or expired."""


def _sign(body_b64: str) -> str:
    return hmac.new(settings.action_token_secret.encode(), body_b64.encode(), hashlib.sha256).hexdigest()


def issue_action_token(action_id: str, payload_hash: str, expires_at: datetime) -> str:
    body = {"action_id": action_id, "payload_hash": payload_hash, "exp": expires_at.isoformat()}
    body_b64 = base64.urlsafe_b64encode(json.dumps(body, sort_keys=True).encode()).decode().rstrip("=")
    return f"{body_b64}.{_sign(body_b64)}"


def verify_action_token(token: str, action_id: str, payload_hash: str) -> None:
    """Raises ActionTokenInvalid; returns None if the token checks out."""
    try:
        body_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise ActionTokenInvalid("malformed action_token") from exc

    if not hmac.compare_digest(signature, _sign(body_b64)):
        raise ActionTokenInvalid("action_token signature does not match")

    try:
        padded = body_b64 + "=" * (-len(body_b64) % 4)
        body = json.loads(base64.urlsafe_b64decode(padded))
        expires_at = datetime.fromisoformat(body["exp"])
    except (ValueError, KeyError) as exc:
        raise ActionTokenInvalid("malformed action_token body") from exc

    if body.get("action_id") != action_id or body.get("payload_hash") != payload_hash:
        raise ActionTokenInvalid("action_token does not match this action_id/payload")
    if datetime.now(timezone.utc) >= expires_at:
        raise ActionTokenInvalid("action_token expired")


def hash_token(token: str) -> str:
    """Stored instead of the raw token, so a leaked ActionRequest row can't
    be replayed — verification still works because verify_action_token
    checks the signature/body of the token the caller presents, and callers
    compare token hashes only to detect a stale/reused token, not to derive
    it."""
    return hashlib.sha256(token.encode()).hexdigest()
