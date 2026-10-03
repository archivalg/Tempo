"""Push and SMS provider interfaces (mobile foundation).

Honest semantics: a provider `accepted` result means the provider took the message, nothing more. Receipts say whether the provider handed it to
Apple/Google; only the app's own acknowledgement says the device saw it. Nothing here claims a person was reached.

No real SMS provider is implemented: the interface, a mock and a 'disabled' provider exist so tenant settings, caps and usage tracking can be built
and tested without paid messaging. Wiring a real vendor needs an account, a sender and a decision on one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import settings


@dataclass
class PushResult:
    status: str                      # accepted | rejected | failed | device_unregistered | not_sent
    provider_ref: str | None = None
    error: str | None = None


class PushProvider(Protocol):
    name: str

    def send(self, token: str, title: str, body: str, data: dict) -> PushResult: ...
    def receipts(self, refs: list[str]) -> dict[str, tuple[str, str | None]]: ...   # ref -> ("ok" | "error", detail)


class DisabledPushProvider:
    name = "disabled"

    def send(self, token: str, title: str, body: str, data: dict) -> PushResult:
        return PushResult("not_sent", error="push provider is not configured (TEMPO_PUSH_PROVIDER=disabled)")

    def receipts(self, refs: list[str]) -> dict[str, tuple[str, str | None]]:
        return {}


@dataclass
class MockPushProvider:
    """Records what would be sent. Tokens containing 'unregistered' or 'fail' simulate those provider answers."""
    name: str = "mock"
    sent: list[dict] = field(default_factory=list)

    def send(self, token: str, title: str, body: str, data: dict) -> PushResult:
        self.sent.append({"token": token, "title": title, "body": body, "data": data})
        if "unregistered" in token:
            return PushResult("device_unregistered", error="DeviceNotRegistered")
        if "fail" in token:
            return PushResult("failed", error="simulated provider failure")
        return PushResult("accepted", provider_ref=f"mock-{len(self.sent)}")

    def receipts(self, refs: list[str]) -> dict[str, tuple[str, str | None]]:
        return {r: ("ok", None) for r in refs}


class ExpoPushProvider:
    """Expo's push service, which forwards to APNs and FCM. Needs the app built with Expo credentials for Apple/Google configured in the Expo account."""
    name = "expo"
    SEND = "https://exp.host/--/api/v2/push/send"
    RECEIPTS = "https://exp.host/--/api/v2/push/getReceipts"

    def _headers(self) -> dict:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if settings.expo_access_token:
            h["Authorization"] = f"Bearer {settings.expo_access_token}"
        return h

    def send(self, token: str, title: str, body: str, data: dict) -> PushResult:
        try:
            r = httpx.post(self.SEND, headers=self._headers(), timeout=10,
                           content=json.dumps({"to": token, "title": title, "body": body, "data": data, "sound": "default", "priority": "high"}))
        except httpx.HTTPError as e:
            return PushResult("failed", error=f"network: {type(e).__name__}")
        if r.status_code >= 500:
            return PushResult("failed", error=f"provider {r.status_code}")
        if r.status_code >= 400:
            return PushResult("rejected", error=f"provider {r.status_code}")
        d = (r.json().get("data") or {})
        if d.get("status") == "ok":
            return PushResult("accepted", provider_ref=d.get("id"))
        if (d.get("details") or {}).get("error") == "DeviceNotRegistered":
            return PushResult("device_unregistered", error="DeviceNotRegistered")
        return PushResult("rejected", error=d.get("message", "provider rejected")[:200])

    def receipts(self, refs: list[str]) -> dict[str, tuple[str, str | None]]:
        if not refs:
            return {}
        try:
            r = httpx.post(self.RECEIPTS, headers=self._headers(), timeout=10, content=json.dumps({"ids": refs}))
            data = (r.json().get("data") or {}) if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}
        return {k: (v.get("status", "error"), (v.get("details") or {}).get("error") or v.get("message")) for k, v in data.items()}


_mock = MockPushProvider()


def get_push_provider() -> PushProvider:
    p = settings.push_provider
    if p == "mock":
        return _mock
    if p == "expo":
        return ExpoPushProvider()
    return DisabledPushProvider()


def mock_push() -> MockPushProvider:
    return _mock


# ------------------------------------------------------------------------------------------------------------------ SMS
@dataclass
class SmsResult:
    status: str                      # sent | failed | not_sent
    error: str | None = None
    segments: int = 1


class SmsProvider(Protocol):
    name: str

    def send(self, to_e164: str, text: str) -> SmsResult: ...


class DisabledSmsProvider:
    name = "disabled"

    def send(self, to_e164: str, text: str) -> SmsResult:
        return SmsResult("not_sent", "SMS provider is not configured")


@dataclass
class MockSmsProvider:
    name: str = "mock"
    sent: list[dict] = field(default_factory=list)

    def send(self, to_e164: str, text: str) -> SmsResult:
        self.sent.append({"to": to_e164, "text": text})
        return SmsResult("sent", segments=1 + len(text) // 160)


_sms = MockSmsProvider()


def get_sms_provider() -> SmsProvider:
    return _sms if settings.sms_provider == "mock" else DisabledSmsProvider()


def mock_sms() -> MockSmsProvider:
    return _sms
