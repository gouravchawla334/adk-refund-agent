"""Read-only tools: order lookup, logistics, policy and fraud checks."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from .. import db
from ..config import (
    DELIVERED_STATUS,
    FRAUD_SCORE_THRESHOLD,
    WORKFLOW_STATE_DEFAULTS,
    cents_to_usd,
)
from ..schemas.inputs import validate_order_id

_INVALID_ID_MSG = (
    "That Order ID doesn't look right. Please double-check it; it should look like ORD-12345."
)
_NOT_FOUND_MSG = (
    "This order is not available in our system. Please double-check the Order ID."
)


def get_order_details(order_id: str, tool_context: ToolContext) -> dict:
    """Look up an order by its Order ID and return its items and totals.

    Args:
        order_id: The customer's Order ID in the format ORD-12345.

    Returns:
        A dict with `status` ("FOUND", "NOT_FOUND" or "INVALID_ORDER_ID"). When FOUND,
        `order` holds order_id, customer_id, category_id, category_name, item_description,
        item_condition, items_subtotal_usd, shipping_usd and total_paid_usd.
        Otherwise `message` explains the problem in plain English.
    """
    try:
        clean = validate_order_id(order_id)
    except ValueError:
        return {"status": "INVALID_ORDER_ID", "message": _INVALID_ID_MSG}

    row = db.fetch_order(clean)
    if row is None:
        return {"status": "NOT_FOUND", "message": _NOT_FOUND_MSG}

    state = tool_context.state
    if state.get("order_id") != clean:  # new order => start a fresh workflow
        for key, default in WORKFLOW_STATE_DEFAULTS.items():
            state[key] = default
    state["order_loaded"] = True
    state["order_id"] = clean
    state["customer_id"] = row["customer_id"]
    state["category_id"] = row["category_id"]

    policy = db.fetch_policy(row["category_id"])
    return {
        "status": "FOUND",
        "order": {
            "order_id": row["order_id"],
            "customer_id": row["customer_id"],
            "category_id": row["category_id"],
            "category_name": policy["category_name"] if policy else row["category_id"],
            "item_description": row["item_description"],
            "item_condition": row["item_condition"],
            "items_subtotal_usd": cents_to_usd(row["items_subtotal_cents"]),
            "shipping_usd": cents_to_usd(row["shipping_cents"]),
            "total_paid_usd": cents_to_usd(row["total_cents"]),
            "refund_status": row["refund_status"],
            # Internal fields below are pruned by after_tool_callback before the LLM sees them.
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "internal_metadata": {"source": "local_sqlite", "schema_version": 1},
        },
    }


def get_return_logistics(order_id: str, tool_context: ToolContext) -> dict:
    """Check where the customer's return package currently is.

    Args:
        order_id: The Order ID in the format ORD-12345.

    Returns:
        A dict with `status`, `carrier_status`, `carrier_name`, `tracking_number`,
        `arrived_at_warehouse` (True only when the package was scanned at the warehouse)
        and a plain-English `message`.
    """
    try:
        clean = validate_order_id(order_id)
    except ValueError:
        return {"status": "INVALID_ORDER_ID", "message": _INVALID_ID_MSG}

    row = db.fetch_logistics(clean)
    if row is None:
        return {"status": "NOT_FOUND", "message": _NOT_FOUND_MSG}

    arrived = row["carrier_status"] == DELIVERED_STATUS
    tool_context.state["logistics_verified"] = arrived
    message = (
        "The return package has been scanned at our warehouse."
        if arrived
        else "The return package has not arrived at our warehouse yet."
    )
    return {
        "status": "FOUND",
        "carrier_status": row["carrier_status"],
        "carrier_name": row["carrier_name"],
        "tracking_number": row["tracking_number"],
        "arrived_at_warehouse": arrived,
        "message": message,
        "last_scan_ts": row["last_scan_ts"],  # pruned before reaching the LLM
    }


def fetch_refund_policy(category_id: str, tool_context: ToolContext) -> dict:
    """Fetch the return window and restocking-fee percentage for a product category.

    Args:
        category_id: The category_id returned by get_order_details (e.g. CAT-APPAREL).

    Returns:
        A dict with `status`, `category_id`, `category_name`, `return_window_days` and
        `restocking_fee_pct` (percentage applied to the item subtotal unless waived).
    """
    row = db.fetch_policy(category_id)
    if row is None:
        return {"status": "NOT_FOUND", "message": "No refund policy found for this category."}
    return {
        "status": "FOUND",
        "category_id": row["category_id"],
        "category_name": row["category_name"],
        "return_window_days": row["return_window_days"],
        "restocking_fee_pct": row["restocking_fee_pct"],
    }


def check_fraud_score(customer_id: str, order_id: str, tool_context: ToolContext) -> dict:
    """Run the internal fraud screen for a customer and order.

    Args:
        customer_id: The customer_id returned by get_order_details (e.g. CUST-1001).
        order_id: The Order ID in the format ORD-12345.

    Returns:
        A dict with `status`, `fraud_flagged` (bool) and `fraud_score`. Never reveal
        these values to the customer.
    """
    try:
        clean = validate_order_id(order_id)
    except ValueError:
        return {"status": "INVALID_ORDER_ID", "message": _INVALID_ID_MSG}

    score = db.fetch_fraud_score(customer_id, clean)
    if score is None:
        return {"status": "NOT_FOUND", "message": "No fraud record found for this order."}

    flagged = score >= FRAUD_SCORE_THRESHOLD
    tool_context.state["fraud_checked"] = True
    tool_context.state["fraud_flagged"] = flagged
    return {"status": "OK", "fraud_score": score, "fraud_flagged": flagged}
