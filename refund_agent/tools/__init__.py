"""Central tool registry. Order mirrors the workflow stages."""

from .compute_tools import calculate_refund_amount
from .read_tools import (
    check_fraud_score,
    fetch_refund_policy,
    get_order_details,
    get_return_logistics,
)
from .write_tools import capture_return_feedback, create_hitl_ticket, execute_payment_refund

ALL_TOOLS = [
    get_order_details,
    capture_return_feedback,
    get_return_logistics,
    fetch_refund_policy,
    check_fraud_score,
    calculate_refund_amount,
    execute_payment_refund,
    create_hitl_ticket,
]

__all__ = ["ALL_TOOLS"]
