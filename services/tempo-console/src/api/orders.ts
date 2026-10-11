import { apiRequest } from './client'

// Mirrors app.api.v1.orders.get_order / complete_order. `order_id` accepts either Tempo's internal id
// or the customer's own order_ref (app/api/v1/orders.py::_get_owned_order resolves either).
export interface OrderLifecycle {
  order_ref: string
  status: string
  units: number | null
  committed_units: number
  fulfilled_units: number
  outstanding_quantity: number | null
  available_for_planning: number | null
}
export interface CompleteOrderResponse {
  order_ref: string
  units: number
  fulfilled_units: number
  confirmed_this_call: number
  status: string
}

export const getOrder = (orderId: string) => apiRequest<OrderLifecycle>(`/orders/${encodeURIComponent(orderId)}`)
export const completeOrder = (orderId: string, quantity: number) =>
  apiRequest<CompleteOrderResponse>(`/orders/${encodeURIComponent(orderId)}/complete`, { method: 'POST', body: { quantity } })
