"""Tool-level callbacks: sequence enforcement, parameter integrity, caps and output pruning."""

from __future__ import annotations

from typing import Any, Dict, Optional

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from ..config import (
    AUTO_APPROVE_LIMIT_CENTS,
    ESCALATION_AMOUNT,
    ESCALATION_FRAUD,
    PRUNE_KEYS,
    PRUNED_TOOLS,
    to_cents,
)
from ..schemas.inputs import validate_order_id


def _blocked(code: str, message: str, next_action: str, **extra: Any) -> Dict[str, Any]:
    """Standard BLOCKED payload returned instead of running the tool."""
    return {
        "status": "BLOCKED",
        "error_code": code,
        "message": message,
        "next_action": next_action,
        **extra,
    }


def _escalation_reason(state: Any) -> Optional[str]:
    """Return the HITL reason code if the case needs Finance review, else None."""
    if state.get("fraud_flagged"):
        return ESCALATION_FRAUD
    verified = state.get("verified_refund_amount")
    if verified is not None and to_cents(verified) > AUTO_APPROVE_LIMIT_CENTS:
        return ESCALATION_AMOUNT
    return None


def before_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict[str, Any]]:
    """Enforce validation, call order and tamper-proof payout parameters.

    Mutates `args` in place (ADK then runs the tool with the corrected arguments) or
    returns a BLOCKED dict to skip the tool entirely.

    Args:
        tool: The tool about to run.
        args: The LLM-supplied arguments.
        tool_context: Tool context exposing session state and invocation_id.

    Returns:
        None to proceed, or a dict that replaces the tool result.
    """
    name = tool.name
    state = tool_context.state

    # 1) Validate the Order ID BEFORE any DB access.
    if "order_id" in args:
        try:
            args["order_id"] = validate_order_id(args["order_id"])
        except ValueError:
            return _blocked(
                "INVALID_ORDER_ID",
                "The Order ID format is invalid.",
                "Ask the customer to double-check their Order ID (format ORD-12345).",
            )
    if name == "get_order_details":
        return None

    # 2) Everything else requires a loaded order, and cannot jump to another one.
    if not state.get("order_loaded"):
        return _blocked(
            "ORDER_NOT_LOADED",
            "No order is loaded yet.",
            "Ask for the Order ID and call get_order_details first.",
        )
    if "order_id" in args and args["order_id"] != state.get("order_id"):
        return _blocked(
            "ORDER_MISMATCH",
            "That Order ID differs from the order being processed.",
            "Call get_order_details for the new order first.",
        )

    # 3) Overwrite identifiers the LLM could tamper with.
    if name == "fetch_refund_policy":
        args["category_id"] = state.get("category_id")
    elif name == "check_fraud_score":
        args["customer_id"] = state.get("customer_id")

    if name == "calculate_refund_amount":
        if not state.get("feedback_captured"):
            return _blocked(
                "FEEDBACK_REQUIRED",
                "Return feedback has not been captured.",
                "Ask the customer for their return reason, then call capture_return_feedback.",
            )
        if not state.get("logistics_verified"):
            return _blocked(
                "LOGISTICS_NOT_VERIFIED",
                "The return package has not been confirmed at the warehouse.",
                "Call get_return_logistics; if not arrived, tell the customer and stop.",
            )
        if not state.get("fraud_checked"):
            return _blocked(
                "FRAUD_CHECK_REQUIRED", "The fraud check has not run.", "Call check_fraud_score first."
            )
        args["reason_category"] = state.get("reason_category")  # customer cannot switch reasons later

    elif name in ("execute_payment_refund", "create_hitl_ticket"):
        verified = state.get("verified_refund_amount")
        if verified is None:
            return _blocked(
                "CALCULATION_REQUIRED",
                "No verified refund amount exists.",
                "Call calculate_refund_amount first.",
            )
        if state.get("calc_invocation_id") == tool_context.invocation_id:
            return _blocked(
                "CONFIRMATION_REQUIRED",
                "The customer has not confirmed the refund amount yet.",
                "Present the breakdown and ask the customer to confirm, then wait.",
            )
        if state.get("refund_executed"):
            return _blocked(
                "ALREADY_PROCESSED",
                "This refund was already paid out.",
                "Tell the customer the refund is complete.",
            )

        reason = _escalation_reason(state)
        if name == "execute_payment_refund":
            if reason is not None:
                return _blocked(
                    "ESCALATION_REQUIRED",
                    "This refund cannot be auto-approved and needs Finance review.",
                    f"Call create_hitl_ticket with order_id and reason_code={reason}.",
                    reason_code=reason,
                )
            cents = to_cents(verified)
            if cents <= 0 or cents > AUTO_APPROVE_LIMIT_CENTS:
                return _blocked(
                    "AMOUNT_INVALID",
                    "The verified amount is not payable.",
                    "Apologize and suggest contacting support.",
                )
            # Tamper-proof payout parameters: LLM-supplied values are discarded.
            args["amount"] = verified
            args["idempotency_key"] = f"IDEMP-{state.get('order_id')}-{cents}"
        else:  # create_hitl_ticket
            if reason is None:
                return _blocked(
                    "ESCALATION_NOT_NEEDED",
                    "This refund can be paid automatically.",
                    "Call execute_payment_refund with just the order ID.",
                )
            args["reason_code"] = reason  # deterministic, not LLM-chosen
    return None


def _prune(value: Any) -> Any:
    """Recursively drop internal timestamp/metadata keys."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if k not in PRUNE_KEYS}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def after_tool_callback(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Strip raw timestamps/metadata from lookup results to save LLM context tokens.

    Args:
        tool: The tool that ran.
        args: The arguments it ran with.
        tool_context: Tool context.
        tool_response: The tool's raw result.

    Returns:
        A pruned copy for pruned tools, else None (response unchanged).
    """
    if tool.name in PRUNED_TOOLS and isinstance(tool_response, dict):
        return _prune(tool_response)
    return None
