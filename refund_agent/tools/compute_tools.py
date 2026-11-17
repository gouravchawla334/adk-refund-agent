"""Pure deterministic refund math. The LLM never computes amounts."""

from __future__ import annotations

from typing import Tuple

from google.adk.tools.tool_context import ToolContext

from .. import db
from ..config import AUTO_APPROVE_LIMIT_CENTS, DELIVERED_STATUS, FAULT_REASONS
from ..schemas.inputs import ReturnReason, validate_order_id
from ..schemas.outputs import RefundBreakdown


def compute_refund_cents(
    items_cents: int, shipping_cents: int, fee_pct: int, reason_category: str
) -> Tuple[int, int, int]:
    """Pure integer-cent refund math (no I/O, no state).

    Rules: restocking fee is 0% for DEFECTIVE / NOT_AS_PICTURED, otherwise `fee_pct`
    of the item subtotal (half-up rounding). Shipping is refunded only on those
    merchant-fault reasons.

    Args:
        items_cents: Item subtotal in cents.
        shipping_cents: Shipping paid in cents.
        fee_pct: Category restocking fee percentage (e.g. 10).
        reason_category: One of the return reason categories.

    Returns:
        Tuple of (restocking_fee_cents, shipping_refund_cents, net_refund_cents).
    """
    is_fault = reason_category in FAULT_REASONS
    effective_pct = 0 if is_fault else fee_pct
    fee_cents = (items_cents * effective_pct + 50) // 100  # half-up
    shipping_refund = shipping_cents if is_fault else 0
    net = items_cents - fee_cents + shipping_refund
    return fee_cents, shipping_refund, net


def calculate_refund_amount(order_id: str, reason_category: str, tool_context: ToolContext) -> dict:
    """Calculate the exact net refund for an order. Call only after feedback, logistics and fraud checks.

    Args:
        order_id: The Order ID in the format ORD-12345.
        reason_category: One of DEFECTIVE, WRONG_SIZE, NOT_AS_PICTURED, NO_LONGER_NEEDED, OTHER.

    Returns:
        A dict with `status` and `breakdown` (items_subtotal_usd, restocking_fee_pct,
        restocking_fee_usd, shipping_refund_usd, net_refund_usd, exceeds_auto_approve_limit).
        Present these numbers to the customer exactly as returned.
    """
    try:
        clean = validate_order_id(order_id)
        reason = ReturnReason(reason_category).value
    except ValueError:
        return {"status": "INVALID_INPUT", "message": "Invalid order ID or return reason."}

    order = db.fetch_order(clean)
    if order is None:
        return {"status": "NOT_FOUND", "message": "This order is not available in our system."}

    logistics = db.fetch_logistics(clean)
    if logistics is None or logistics["carrier_status"] != DELIVERED_STATUS:
        return {
            "status": "NOT_ELIGIBLE",
            "message": "The return package has not arrived at our warehouse yet.",
        }

    policy = db.fetch_policy(order["category_id"])
    if policy is None:
        return {"status": "NOT_FOUND", "message": "No refund policy found for this category."}

    fee_pct = int(policy["restocking_fee_pct"])
    fee_cents, ship_cents, net_cents = compute_refund_cents(
        order["items_subtotal_cents"], order["shipping_cents"], fee_pct, reason
    )
    breakdown = RefundBreakdown.from_cents(
        clean,
        reason,
        order["items_subtotal_cents"],
        0 if reason in FAULT_REASONS else fee_pct,
        fee_cents,
        ship_cents,
        net_cents,
    )

    state = tool_context.state
    state["verified_refund_amount"] = breakdown.net_refund_usd
    state["refund_breakdown"] = breakdown.model_dump()
    state["calc_invocation_id"] = tool_context.invocation_id  # confirmation must come in a later turn
    return {
        "status": "CALCULATED",
        "breakdown": breakdown.model_dump(),
        "requires_finance_review": net_cents > AUTO_APPROVE_LIMIT_CENTS,
    }
