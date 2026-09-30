"""Identity-provider adapter (ADR-0001: the production IdP is still an open decision).

`IdentityProvider` is the only surface the rest of Tempo sees. `OidcProvider`
is a standards-based Authorization Code + PKCE client that verifies the ID token's
signature (JWKS with key rotation via PyJWKClient), issuer, audience, expiry and
nonce. `DevIdentityProvider` is a restricted local stand-in: it only *asserts an
identity* — it grants nothing, since authority always comes from Tempo-owned
memberships — and refuses to run outside TEMPO_ENV=local|test.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings
from app.errors import AuthInvalid


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    mfa: bool  # IdP asserted a second factor (amr)


class IdentityProvider(Protocol):
    name: str

    def authorization_url(self, state: str, nonce: str, code_challenge: str, redirect_uri: str) -> str: ...
    def exchange(self, code: str, code_verifier: str, nonce: str, redirect_uri: str) -> VerifiedIdentity: ...


MFA_AMR = {"mfa", "otp", "hwk", "swk", "fpt", "pin"}


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class OidcProvider:
    name = "oidc"

    def __init__(self, issuer: str, audience: str, jwks_url: str, client_secret: str = "") -> None:
        self.issuer, self.audience, self.client_secret = issuer.rstrip("/"), audience, client_secret
        self._jwks = PyJWKClient(jwks_url, cache_keys=True)
        self._disco: dict | None = None

    def _discovery(self) -> dict:
        if self._disco is None:
            r = httpx.get(f"{self.issuer}/.well-known/openid-configuration", timeout=10)
            r.raise_for_status()
            self._disco = r.json()
        return self._disco

    def authorization_url(self, state, nonce, code_challenge, redirect_uri) -> str:
        q = urlencode({"response_type": "code", "client_id": self.audience, "redirect_uri": redirect_uri,
                       "scope": "openid email profile", "state": state, "nonce": nonce,
                       "code_challenge": code_challenge, "code_challenge_method": "S256"})
        return f"{self._discovery()['authorization_endpoint']}?{q}"

    def exchange(self, code, code_verifier, nonce, redirect_uri) -> VerifiedIdentity:
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": self.audience, "code_verifier": code_verifier}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = httpx.post(self._discovery()["token_endpoint"], data=data, timeout=10)
        if r.status_code != 200:
            raise AuthInvalid("identity provider rejected the login")
        return self.verify_id_token(r.json().get("id_token", ""), nonce)

    def verify_id_token(self, id_token: str, nonce: str) -> VerifiedIdentity:
        try:
            key = self._jwks.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(id_token, key, algorithms=["RS256", "ES256"], audience=self.audience,
                                issuer=self.issuer, options={"require": ["exp", "iss", "aud", "sub"]})
        except jwt.PyJWTError:
            raise AuthInvalid("identity token failed verification") from None
        if not hmac_eq(claims.get("nonce", ""), nonce):
            raise AuthInvalid("identity token nonce mismatch")
        amr = set(claims.get("amr", []) or [])
        return VerifiedIdentity(claims["sub"], (claims.get("email") or "").lower() or None,
                                bool(claims.get("email_verified", False)), claims.get("name"),
                                bool(amr & MFA_AMR))


def hmac_eq(a: str, b: str) -> bool:
    import hmac
    return bool(a) and hmac.compare_digest(a, b)


class DevIdentityProvider:
    """NEVER production authentication. Asserts whatever identity is posted to it."""

    name = "dev-local"

    def assert_identity(self, subject: str, email: str | None, name: str | None, mfa: bool) -> VerifiedIdentity:
        if settings.env not in ("local", "test") or not settings.dev_idp_enabled:
            raise AuthInvalid("dev identity provider is disabled")
        return VerifiedIdentity(subject, email.lower() if email else None, bool(email), name, mfa)


_oidc: OidcProvider | None = None


def get_oidc() -> OidcProvider | None:
    global _oidc
    if _oidc is None and settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url:
        from os import environ
        _oidc = OidcProvider(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url,
                             environ.get("TEMPO_OIDC_CLIENT_SECRET", ""))
    return _oidc
