"""Local SQLite store with auto-initialization, seed data and parameterized queries.

Money is stored as integer cents. Every query uses `?` placeholders; no SQL is ever
built from user input via string formatting.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Set, Tuple

from .config import get_db_path
from .schemas.inputs import validate_order_id

_INITIALIZED: Set[str] = set()
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    item_description TEXT NOT NULL,
    item_condition TEXT NOT NULL,
    items_subtotal_cents INTEGER NOT NULL,
    shipping_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    fraud_score REAL NOT NULL DEFAULT 0.0,
    refund_status TEXT NOT NULL DEFAULT 'NONE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS return_logistics (
    order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
    carrier_name TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    carrier_status TEXT NOT NULL,
    last_scan_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    category_id TEXT PRIMARY KEY,
    category_name TEXT NOT NULL,
    return_window_days INTEGER NOT NULL,
    restocking_fee_pct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS return_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    reason_category TEXT NOT NULL,
    customer_comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- Audit tables (additive): payouts enforce idempotency, tickets hold Finance HITL cases.
CREATE TABLE IF NOT EXISTS refund_payouts (
    idempotency_key TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    amount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hitl_tickets (
    ticket_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    reason_code TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_FINANCE_REVIEW',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seed(conn: sqlite3.Connection) -> None:
    """Insert the three canonical test scenarios (idempotent)."""
    ts = _now()
    conn.executemany(
        "INSERT OR IGNORE INTO policies VALUES (?, ?, ?, ?)",
        [
            ("CAT-APPAREL", "Apparel", 30, 10),
            ("CAT-ELECTRONICS", "Electronics", 14, 15),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO orders (order_id, customer_id, category_id, item_description, "
        "item_condition, items_subtotal_cents, shipping_cents, total_cents, fraud_score, "
        "refund_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'NONE', ?, ?)",
        [
            # Scenario 1: auto-refund eligible ($90.00 items + $10.00 shipping = $100.00)
            ("ORD-98765", "CUST-1001", "CAT-APPAREL", "Wool winter jacket",
             "UNOPENED_NEW", 9000, 1000, 10000, 0.05, ts, ts),
            # Scenario 2: exceeds $150.00 cap -> Finance HITL escalation
            ("ORD-55555", "CUST-1002", "CAT-ELECTRONICS", "Noise-cancelling headphones",
             "OPENED_LIKE_NEW", 24000, 0, 24000, 0.10, ts, ts),
            # Scenario 3: still in transit, not yet scanned at warehouse
            ("ORD-11111", "CUST-1003", "CAT-APPAREL", "Running shoes",
             "UNOPENED_NEW", 8000, 0, 8000, 0.02, ts, ts),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO return_logistics VALUES (?, ?, ?, ?, ?)",
        [
            ("ORD-98765", "UPS", "1Z999AA10123456784", "DELIVERED_AT_WAREHOUSE", ts),
            ("ORD-55555", "FedEx", "794644790138", "DELIVERED_AT_WAREHOUSE", ts),
            ("ORD-11111", "USPS", "9400111899223197428490", "IN_TRANSIT", ts),
        ],
    )


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Yield a connection, auto-creating schema/seed data on first use per DB path.

    Commits on success, rolls back on error, always closes.
    """
    path = get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if path not in _INITIALIZED:
            with _LOCK:
                conn.executescript(_SCHEMA)
                _seed(conn)
                conn.commit()
                _INITIALIZED.add(path)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create and seed the database if it does not exist yet."""
    with db_session():
        pass


def fetch_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Return the order row as a dict, or None. Raises ValueError on a malformed ID."""
    clean = validate_order_id(order_id)
    with db_session() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (clean,)).fetchone()
    return dict(row) if row else None


def fetch_logistics(order_id: str) -> Optional[Dict[str, Any]]:
    """Return the return-logistics row for an order, or None."""
    clean = validate_order_id(order_id)
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM return_logistics WHERE order_id = ?", (clean,)
        ).fetchone()
    return dict(row) if row else None


def fetch_policy(category_id: str) -> Optional[Dict[str, Any]]:
    """Return the refund policy row for a product category, or None."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM policies WHERE category_id = ?", (category_id,)
        ).fetchone()
    return dict(row) if row else None


def fetch_fraud_score(customer_id: str, order_id: str) -> Optional[float]:
    """Return the stored fraud score for a customer/order pair, or None."""
    clean = validate_order_id(order_id)
    with db_session() as conn:
        row = conn.execute(
            "SELECT fraud_score FROM orders WHERE order_id = ? AND customer_id = ?",
            (clean, customer_id),
        ).fetchone()
    return float(row["fraud_score"]) if row else None


def insert_feedback(order_id: str, reason_category: str, customer_comment: str) -> int:
    """Persist return feedback and return its row id."""
    clean = validate_order_id(order_id)
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO return_feedback (order_id, reason_category, customer_comment, created_at) "
            "VALUES (?, ?, ?, ?)",
            (clean, reason_category, customer_comment, _now()),
        )
        return int(cur.lastrowid)


def insert_payout(order_id: str, amount_cents: int, idempotency_key: str) -> bool:
    """Record a payout idempotently. Returns True if newly created, False if it already existed."""
    clean = validate_order_id(order_id)
    with db_session() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO refund_payouts (idempotency_key, order_id, amount_cents, created_at) "
            "VALUES (?, ?, ?, ?)",
            (idempotency_key, clean, amount_cents, _now()),
        )
        created = cur.rowcount == 1
        if created:
            conn.execute(
                "UPDATE orders SET refund_status = 'REFUNDED', updated_at = ? WHERE order_id = ?",
                (_now(), clean),
            )
        return created


def insert_ticket(order_id: str, reason_code: str, amount_cents: int) -> Tuple[str, bool]:
    """Create a Finance HITL ticket idempotently. Returns (ticket_id, newly_created)."""
    clean = validate_order_id(order_id)
    ticket_id = f"HITL-{clean}-{reason_code}"
    with db_session() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO hitl_tickets (ticket_id, order_id, reason_code, amount_cents, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticket_id, clean, reason_code, amount_cents, _now()),
        )
        return ticket_id, cur.rowcount == 1
