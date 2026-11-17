"""Input validators: Order ID regex and the closed set of return reasons."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, field_validator

from ..config import MAX_COMMENT_CHARS, ORDER_ID_REGEX

_ORDER_ID_PATTERN = re.compile(ORDER_ID_REGEX)


class ReturnReason(str, Enum):
    """Allowed return reason categories."""

    DEFECTIVE = "DEFECTIVE"
    WRONG_SIZE = "WRONG_SIZE"
    NOT_AS_PICTURED = "NOT_AS_PICTURED"
    NO_LONGER_NEEDED = "NO_LONGER_NEEDED"
    OTHER = "OTHER"


def validate_order_id(order_id: str) -> str:
    """Validate an Order ID against ^ORD-[0-9]{5}$ BEFORE it can reach SQLite.

    Uses fullmatch so a trailing newline cannot sneak past `$`.

    Args:
        order_id: Raw order ID string.

    Returns:
        The cleaned (whitespace-trimmed) Order ID.

    Raises:
        ValueError: If the value is not a string matching the Order ID format.
    """
    if not isinstance(order_id, str):
        raise ValueError("Order ID must be a string.")
    cleaned = order_id.strip()
    if not _ORDER_ID_PATTERN.fullmatch(cleaned):
        raise ValueError("Order ID must look like ORD-12345.")
    return cleaned


class OrderIdInput(BaseModel):
    """Validated order-ID payload."""

    order_id: str

    @field_validator("order_id")
    @classmethod
    def _check_order_id(cls, value: str) -> str:
        return validate_order_id(value)


class ReturnFeedbackInput(BaseModel):
    """Validated return-feedback payload."""

    order_id: str
    reason_category: ReturnReason
    customer_comment: str = ""

    @field_validator("order_id")
    @classmethod
    def _check_order_id(cls, value: str) -> str:
        return validate_order_id(value)

    @field_validator("customer_comment", mode="before")
    @classmethod
    def _clean_comment(cls, value: object) -> str:
        text = "" if value is None else str(value)
        return "".join(ch for ch in text if ch.isprintable())[:MAX_COMMENT_CHARS].strip()
