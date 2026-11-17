"""Central configuration: financial caps, token limits, regex rules and session-state defaults.

Everything tunable lives here so the business rules are auditable in one place.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, Union

# --- Model & generation ------------------------------------------------------
MODEL_NAME: str = "gemini-2.5-flash"
AGENT_NAME: str = "RefundOrchestratorAgent"
TEMPERATURE: float = 0.0
MAX_OUTPUT_TOKENS: int = 300

# --- Financial rules ---------------------------------------------------------
AUTO_APPROVE_LIMIT_USD: Decimal = Decimal("150.00")
AUTO_APPROVE_LIMIT_CENTS: int = 15000
FRAUD_SCORE_THRESHOLD: float = 0.80  # score >= threshold => fraud_flagged

# --- Validation rules --------------------------------------------------------
ORDER_ID_REGEX: str = r"^ORD-[0-9]{5}$"
IDEMPOTENCY_KEY_REGEX: str = r"^IDEMP-ORD-[0-9]{5}-[0-9]+$"
MAX_COMMENT_CHARS: int = 500

# --- Business vocabulary -----------------------------------------------------
RETURN_REASONS = (
    "DEFECTIVE",
    "WRONG_SIZE",
    "NOT_AS_PICTURED",
    "NO_LONGER_NEEDED",
    "OTHER",
)
# Merchant-fault reasons: restocking fee waived AND shipping refunded.
FAULT_REASONS = frozenset({"DEFECTIVE", "NOT_AS_PICTURED"})
DELIVERED_STATUS: str = "DELIVERED_AT_WAREHOUSE"

ESCALATION_AMOUNT: str = "AMOUNT_EXCEEDS_LIMIT"
ESCALATION_FRAUD: str = "FRAUD_FLAGGED"

# --- Guardrail messages ------------------------------------------------------
OFF_TOPIC_RESPONSE: str = (
    "I am a refund agent only and can only help you process returns and refunds."
)
LOOP_BREAK_MESSAGE: str = (
    "I'm having trouble moving this forward. Please double-check your Order ID "
    "(it looks like ORD-12345) and tell me why you are returning the item. "
    "If the problem continues, please contact our support team for help."
)
REPEAT_LIMIT: int = 2  # identical consecutive assistant messages tolerated as repeats

# --- Database ----------------------------------------------------------------
DB_FILENAME: str = "local_refund_store.db"
DEFAULT_DB_PATH: Path = Path(__file__).resolve().parent.parent / DB_FILENAME


def get_db_path() -> str:
    """Return the SQLite path, honoring the REFUND_DB_PATH override (read at call time)."""
    return os.environ.get("REFUND_DB_PATH", str(DEFAULT_DB_PATH))


# --- Session state -----------------------------------------------------------
# Keys reset whenever the customer switches to a different order.
WORKFLOW_STATE_DEFAULTS: Dict[str, Any] = {
    "order_loaded": False,
    "order_id": None,
    "customer_id": None,
    "category_id": None,
    "feedback_captured": False,
    "reason_category": None,
    "logistics_verified": False,
    "fraud_checked": False,
    "fraud_flagged": False,
    "verified_refund_amount": None,
    "refund_breakdown": None,
    "calc_invocation_id": None,
    "refund_executed": False,
    "ticket_id": None,
}
# Anti-loop tracking survives order switches.
LOOP_STATE_DEFAULTS: Dict[str, Any] = {
    "last_assistant_norm": "",
    "repeat_count": 0,
}
STATE_DEFAULTS: Dict[str, Any] = {**WORKFLOW_STATE_DEFAULTS, **LOOP_STATE_DEFAULTS}

# Keys removed from tool output before it reaches the LLM context.
PRUNED_TOOLS = frozenset({"get_order_details", "get_return_logistics"})
PRUNE_KEYS = frozenset(
    {"created_at", "updated_at", "last_scan_ts", "internal_metadata", "ingested_at"}
)


# --- Money helpers (integer cents everywhere; floats only at the display edge) --
def to_cents(amount: Union[int, float, str, Decimal]) -> int:
    """Convert a dollar amount to integer cents using half-up rounding."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_usd(cents: int) -> float:
    """Convert integer cents to a dollar float rounded to 2 places."""
    return round(cents / 100, 2)
