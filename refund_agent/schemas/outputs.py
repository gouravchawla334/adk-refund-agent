"""Structured output models used for tool results and audit summaries."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from ..config import AUTO_APPROVE_LIMIT_CENTS, cents_to_usd


class RefundBreakdown(BaseModel):
    """Deterministic refund math result (all amounts in USD)."""

    order_id: str
    reason_category: str
    items_subtotal_usd: float
    restocking_fee_pct: int
    restocking_fee_usd: float
    shipping_refund_usd: float
    net_refund_usd: float
    exceeds_auto_approve_limit: bool
    currency: str = "USD"

    @classmethod
    def from_cents(
        cls,
        order_id: str,
        reason_category: str,
        items_cents: int,
        fee_pct: int,
        fee_cents: int,
        shipping_refund_cents: int,
        net_cents: int,
    ) -> "RefundBreakdown":
        """Build a breakdown from integer-cent values."""
        return cls(
            order_id=order_id,
            reason_category=reason_category,
            items_subtotal_usd=cents_to_usd(items_cents),
            restocking_fee_pct=fee_pct,
            restocking_fee_usd=cents_to_usd(fee_cents),
            shipping_refund_usd=cents_to_usd(shipping_refund_cents),
            net_refund_usd=cents_to_usd(net_cents),
            exceeds_auto_approve_limit=net_cents > AUTO_APPROVE_LIMIT_CENTS,
        )


class RefundDecisionSummary(BaseModel):
    """End-of-turn audit record of where a refund case currently stands."""

    order_id: Optional[str] = None
    decision: Literal["NO_ORDER", "IN_PROGRESS", "REFUNDED", "ESCALATED_TO_FINANCE"]
    net_refund_usd: Optional[float] = None
    reason_category: Optional[str] = None
    ticket_id: Optional[str] = None
    fraud_flagged: bool = False
