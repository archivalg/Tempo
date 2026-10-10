"""Explicit order completion confirmation (order-driven-planning): the one supported way (besides a
future correlated actuals import, not yet built) that `Order.fulfilled_units` is ever advanced.

A COMMITTED order_fulfillment run (app/solvers/order_workload.py) only ever writes
`Order.committed_units` — a planned allocation, not a fact about the physical world. Publishing or
committing a roster is a promise of labour, not a confirmation that the labour happened. This
endpoint is the explicit, auditable act of recording that confirmation, kept deliberately separate
from the solver so the two can never be silently conflated. See docs/order-driven-planning.md:
"committed does not mean physically fulfilled."
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, OrderNotFound, ScopeError
from app.models.orders import Order
from app.schemas.tenancy import RequestContext
from sqlalchemy.orm import Session

router = APIRouter(tags=["orders"])


class OrderCompletionRequest(BaseModel):
    quantity: float = Field(gt=0, description="Units of this order newly confirmed as actually completed.")


def _get_owned_order(db: Session, context: RequestContext, order_id: str) -> Order:
    """`order_id` accepts EITHER the opaque internal id OR the customer's own `order_ref` (scoped to
    the caller's granted sites) — a customer-facing caller naturally has the order_ref it uploaded,
    not Tempo's internal id, the same convention `source_ref` already gives workers."""
    order = db.get(Order, order_id)
    if order is None:
        order = db.scalar(select(Order).where(Order.tenant_id == context.tenant_id, Order.order_ref == order_id, Order.site_id.in_(context.site_ids)))
    if order is None or order.tenant_id != context.tenant_id or order.site_id not in context.site_ids:
        raise OrderNotFound(f"order '{order_id}' not found or not visible in caller scope")
    return order


@router.get("/orders/{order_id}")
def get_order(
    order_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deliberately distinguishes two different numbers that are easy to conflate:
    `outstanding_quantity` — how much of this order is NOT yet actually done, in the real world
    (`units - fulfilled_units`); and `available_for_planning` — how much is still safe to schedule in
    a NEW run without double-booking labour another plan already claims
    (`units - max(committed_units, fulfilled_units)`). The two differ exactly when something has been
    committed but not yet confirmed done — the common case for an order mid-shift."""
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission")
    order = _get_owned_order(db, context, order_id)
    units = order.units
    outstanding = None if units is None else round(max(0.0, units - order.fulfilled_units), 3)
    available = None if units is None else round(max(0.0, units - max(order.committed_units, order.fulfilled_units)), 3)
    return {
        "order_ref": order.order_ref, "status": order.status, "units": units,
        "committed_units": round(order.committed_units, 3), "fulfilled_units": round(order.fulfilled_units, 3),
        "outstanding_quantity": outstanding, "available_for_planning": available,
    }


@router.post("/orders/{order_id}/complete")
def complete_order(
    order_id: str,
    body: OrderCompletionRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not context.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan permission required to confirm order completion")
    order = _get_owned_order(db, context, order_id)
    if order.units is None:
        # `lines` requires the same activity-specific unit conversion the solver resolves at run
        # time; confirming completion against it here would risk a different, silently-inconsistent
        # conversion. Rather than guess, this path is refused until the order also states `units`.
        raise ScopeError(f"order '{order_id}' has no `units` quantity to confirm completion against "
                          "(a lines-only order isn't yet supported by this endpoint)")
    before = order.fulfilled_units
    order.fulfilled_units = min(order.units, order.fulfilled_units + body.quantity)
    if order.fulfilled_units >= order.units - 1e-9:
        order.status = "completed"
    db.flush()
    return {
        "order_ref": order.order_ref,
        "units": order.units,
        "fulfilled_units": round(order.fulfilled_units, 3),
        "confirmed_this_call": round(order.fulfilled_units - before, 3),
        "status": order.status,
    }
