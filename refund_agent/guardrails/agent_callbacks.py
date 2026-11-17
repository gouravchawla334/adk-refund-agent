"""Agent-level callbacks: session initialization and end-of-turn audit logging."""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from .. import db
from ..config import STATE_DEFAULTS
from ..schemas.outputs import RefundDecisionSummary

logger = logging.getLogger("refund_agent.audit")


def before_agent_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    """Auto-initialize the database and fill any missing session-state keys.

    Args:
        callback_context: ADK callback context exposing session state.

    Returns:
        None, so normal agent execution continues.
    """
    db.init_db()
    state = callback_context.state
    for key, default in STATE_DEFAULTS.items():
        if key not in state:
            state[key] = default
    return None


def after_agent_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    """Log a structured audit summary of the case after every agent turn.

    Args:
        callback_context: ADK callback context exposing session state.

    Returns:
        None, so the agent's response is left unchanged.
    """
    state = callback_context.state
    if state.get("refund_executed"):
        decision = "REFUNDED"
    elif state.get("ticket_id"):
        decision = "ESCALATED_TO_FINANCE"
    elif state.get("order_loaded"):
        decision = "IN_PROGRESS"
    else:
        decision = "NO_ORDER"

    summary = RefundDecisionSummary(
        order_id=state.get("order_id"),
        decision=decision,
        net_refund_usd=state.get("verified_refund_amount"),
        reason_category=state.get("reason_category"),
        ticket_id=state.get("ticket_id"),
        fraud_flagged=bool(state.get("fraud_flagged")),
    )
    logger.info("refund_audit %s", summary.model_dump_json())
    return None
