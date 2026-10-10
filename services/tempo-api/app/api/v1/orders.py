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

from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, OrderNotFound, ScopeError
from app.models.orders import Order
from app.schemas.tenancy import RequestContext
from sqlalchemy.orm import Session

router = APIRouter(tags=["orders"])


class OrderCompletionRequest(BaseModel):
    quantity: float = Field(gt=0, description="Units of this order newly confirmed as actually completed.")


def _get_owned_order(db: Session, context: RequestContext, order_id: str) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.tenant_id != context.tenant_id or order.site_id not in context.site_ids:
        raise OrderNotFound(f"order '{order_id}' not found or not visible in caller scope")
    return order


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
