"""State-changing tools: feedback capture, payout and Finance HITL ticket creation."""

from __future__ import annotations

import re

from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from .. import db
from ..config import (
    AUTO_APPROVE_LIMIT_CENTS,
    ESCALATION_AMOUNT,
    ESCALATION_FRAUD,
    IDEMPOTENCY_KEY_REGEX,
    cents_to_usd,
    to_cents,
)
from ..schemas.inputs import ReturnFeedbackInput, validate_order_id

_KEY_PATTERN = re.compile(IDEMPOTENCY_KEY_REGEX)


def capture_return_feedback(
    order_id: str, reason_category: str, customer_comment: str, tool_context: ToolContext
) -> dict:
    """Record why the customer is returning the item. Call only after the customer has answered.

    Args:
        order_id: The Order ID in the format ORD-12345.
        reason_category: One of DEFECTIVE, WRONG_SIZE, NOT_AS_PICTURED, NO_LONGER_NEEDED, OTHER.
        customer_comment: The customer's own words about the return (may be empty).

    Returns:
        A dict with `status` ("CAPTURED" or "INVALID_INPUT") and a plain-English `message`.
    """
    try:
        payload = ReturnFeedbackInput(
            order_id=order_id, reason_category=reason_category, customer_comment=customer_comment
        )
    except (ValidationError, ValueError):
        return {
            "status": "INVALID_INPUT",
            "message": "Reason must be DEFECTIVE, WRONG_SIZE, NOT_AS_PICTURED, NO_LONGER_NEEDED or OTHER.",
        }

    if db.fetch_order(payload.order_id) is None:
        return {"status": "NOT_FOUND", "message": "This order is not available in our system."}

    feedback_id = db.insert_feedback(
        payload.order_id, payload.reason_category.value, payload.customer_comment
    )
    tool_context.state["feedback_captured"] = True
    tool_context.state["reason_category"] = payload.reason_category.value
    return {"status": "CAPTURED", "feedback_id": feedback_id, "message": "Thanks, your feedback was saved."}


def execute_payment_refund(
    order_id: str, tool_context: ToolContext, amount: float = 0.0, idempotency_key: str = ""
) -> dict:
    """Pay out the verified refund. Pass ONLY order_id; amount and idempotency_key are injected by the system.

    Args:
        order_id: The Order ID in the format ORD-12345.
        amount: Injected by the system from the verified calculation. Leave unset.
        idempotency_key: Injected by the system (IDEMP-<ORDER_ID>-<CENTS>). Leave unset.

    Returns:
        A dict with `status` ("REFUND_PROCESSED", "ALREADY_PROCESSED" or "REJECTED"),
        `refund_amount_usd` and `transaction_id`.
    """
    try:
        clean = validate_order_id(order_id)
    except ValueError:
        return {"status": "REJECTED", "message": "Invalid order ID."}

    state = tool_context.state
    verified = state.get("verified_refund_amount")
    # Defense in depth: re-validate even though before_tool_callback already did.
    if verified is None or not _KEY_PATTERN.fullmatch(idempotency_key or ""):
        return {"status": "REJECTED", "message": "No verified refund amount or invalid key."}
    cents = to_cents(amount)
    if cents != to_cents(verified) or cents <= 0 or cents > AUTO_APPROVE_LIMIT_CENTS:
        return {"status": "REJECTED", "message": "Amount does not match the verified refund."}
    if idempotency_key != f"IDEMP-{clean}-{cents}":
        return {"status": "REJECTED", "message": "Idempotency key mismatch."}

    created = db.insert_payout(clean, cents, idempotency_key)
    state["refund_executed"] = True
    return {
        "status": "REFUND_PROCESSED" if created else "ALREADY_PROCESSED",
        "refund_amount_usd": cents_to_usd(cents),
        "transaction_id": f"TXN-{idempotency_key}",
    }


def create_hitl_ticket(order_id: str, reason_code: str, tool_context: ToolContext) -> dict:
    """Open a Finance human-in-the-loop review ticket for a refund that cannot be auto-approved.

    Args:
        order_id: The Order ID in the format ORD-12345.
        reason_code: AMOUNT_EXCEEDS_LIMIT or FRAUD_FLAGGED (use the code the blocked payout returned).

    Returns:
        A dict with `status` ("TICKET_CREATED", "TICKET_EXISTS" or "REJECTED"), `ticket_id`
        and a plain-English `message`.
    """
    try:
        clean = validate_order_id(order_id)
    except ValueError:
        return {"status": "REJECTED", "message": "Invalid order ID."}
    if reason_code not in (ESCALATION_AMOUNT, ESCALATION_FRAUD):
        return {"status": "REJECTED", "message": "Unknown escalation reason code."}

    verified = tool_context.state.get("verified_refund_amount")
    amount_cents = to_cents(verified) if verified is not None else 0
    ticket_id, created = db.insert_ticket(clean, reason_code, amount_cents)
    tool_context.state["ticket_id"] = ticket_id
    return {
        "status": "TICKET_CREATED" if created else "TICKET_EXISTS",
        "ticket_id": ticket_id,
        "message": "A Finance team member will review this refund.",
    }
