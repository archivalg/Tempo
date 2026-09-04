"""Event publication — §13.

Phase 0 writes the outbox row (§15.1's "outbox pattern required") and
delivers synchronously to in-process subscribers. Phase F swaps the delivery
side for OCI Streaming/Queue (§17.1, OD-03) without changing this interface
or the DomainEvent envelope shape (§13.2).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.runs import EventRecord
from app.schemas.envelope import DomainEvent

Subscriber = Callable[[DomainEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.append(subscriber)

    def publish(
        self,
        db: Session,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any],
        subject: str | None = None,
        correlation_id: str | None = None,
    ) -> DomainEvent:
        event = DomainEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            subject=subject,
            time=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            payload=payload,
        )
        db.add(
            EventRecord(
                event_id=event.event_id,
                tenant_id=tenant_id,
                event_type=event_type,
                subject=subject,
                correlation_id=correlation_id,
                payload=payload,
                occurred_at=event.time,
            )
        )
        db.flush()
        for subscriber in self._subscribers:
            subscriber(event)
        return event


event_bus = EventBus()
