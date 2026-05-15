"""
Approval Queue — Core System

Every high-risk decision from the daemon goes here instead of
executing directly. Humans approve or reject via the agent or gateway.

Risk levels:
  auto    (< 0.3) → executes immediately, no approval needed
  notify  (< 0.7) → executes but logs a notification
  approve (≥ 0.7) → blocked until human decides
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from database import DB_PATH


# ── Schema ────────────────────────────────────────────────────────────────────

INIT_SQL = """
CREATE TABLE IF NOT EXISTS approval_queue (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    action_payload  TEXT NOT NULL DEFAULT '{}',
    risk_score      REAL NOT NULL DEFAULT 0.5,
    risk_level      TEXT NOT NULL DEFAULT 'approve',
    status          TEXT NOT NULL DEFAULT 'pending',
    decision        TEXT,
    decision_notes  TEXT,
    decided_by      TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    executed_at     TEXT,
    executing_at    TEXT,
    source          TEXT DEFAULT 'daemon'
);
CREATE INDEX IF NOT EXISTS idx_approval_agent  ON approval_queue(agent_id);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_approval_risk   ON approval_queue(risk_level);
"""


def init_approval_queue():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(INIT_SQL)
        conn.commit()
    finally:
        conn.close()


# ── Risk Scoring ──────────────────────────────────────────────────────────────

class RiskLevel:
    AUTO    = "auto"     # executes without approval
    NOTIFY  = "notify"   # executes with notification
    APPROVE = "approve"  # blocked until approved


# Action type → base risk scores (impact, reversibility, sensitivity)
ACTION_RISK_MAP = {
    # Memory
    "memory.store":             (0.1, 0.9, 0.2),  # low risk — easily reversible
    "memory.delete_low":        (0.3, 0.4, 0.3),  # medium — some data loss
    "memory.delete_important":  (0.8, 0.1, 0.7),  # high — permanent loss
    "memory.bulk_delete":       (0.9, 0.1, 0.8),  # very high
    # Goals
    "goal.create":              (0.2, 0.8, 0.1),
    "goal.cancel":              (0.6, 0.4, 0.3),
    "goal.reprioritize":        (0.4, 0.6, 0.2),
    # Reflection
    "reflection.analyze":       (0.1, 1.0, 0.1),
    # External
    "external.webhook":         (0.7, 0.3, 0.6),
    "external.api_call":        (0.8, 0.2, 0.7),
    "external.message":         (0.9, 0.1, 0.8),
    # System
    "system.maintenance":       (0.3, 0.7, 0.1),
    "system.bulk_operation":    (0.7, 0.3, 0.5),
}


def calculate_risk(
    action_type: str,
    action_payload: dict,
    custom_impact: Optional[float] = None
) -> tuple[float, str]:
    """
    Calculate risk score and level for an action.

    Returns (risk_score: float, risk_level: str)

    Score formula:
      impact       * 0.4   → how much damage if wrong
      reversibility* 0.3   → can we undo this? (inverted — high reversibility = low risk)
      sensitivity  * 0.3   → data sensitivity
    """
    base = ACTION_RISK_MAP.get(action_type, (0.5, 0.5, 0.5))
    impact, reversibility, sensitivity = base

    if custom_impact is not None:
        impact = custom_impact

    # Reversibility is inverted: high reversibility = low risk contribution
    risk_score = (
        impact * 0.4 +
        (1.0 - reversibility) * 0.3 +
        sensitivity * 0.3
    )
    risk_score = round(min(1.0, max(0.0, risk_score)), 3)

    if risk_score < 0.3:
        level = RiskLevel.AUTO
    elif risk_score < 0.7:
        level = RiskLevel.NOTIFY
    else:
        level = RiskLevel.APPROVE

    return risk_score, level


# ── Queue Operations ──────────────────────────────────────────────────────────

def enqueue(
    agent_id: str,
    title: str,
    description: str,
    action_type: str,
    action_payload: dict,
    risk_score: float,
    risk_level: str,
    source: str = "daemon"
) -> dict:
    """
    Add a decision to the approval queue.
    Returns the queued item dict.
    """
    item_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO approval_queue
            (id, agent_id, title, description, action_type, action_payload,
             risk_score, risk_level, status, created_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (item_id, agent_id, title, description, action_type,
             json.dumps(action_payload), risk_score, risk_level, now, source)
        )
        conn.commit()
        logger.info(
            f"[approval] enqueued '{title}' "
            f"risk={risk_score} level={risk_level} agent={agent_id}"
        )
        return {
            "id": item_id,
            "title": title,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "status": "pending",
            "created_at": now,
        }
    finally:
        conn.close()


def submit_decision(
    item_id: str,
    agent_id: str,
    decision: str,           # "approved" | "rejected"
    notes: str = "",
    decided_by: str = "human"
) -> Optional[dict]:
    """
    Submit a human decision on a pending approval.
    Returns updated item or None if not found.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    try:
        row = conn.execute(
            "SELECT * FROM approval_queue WHERE id = ? AND agent_id = ? AND status = 'pending'",
            (item_id, agent_id)
        ).fetchone()

        if not row:
            return None

        conn.execute(
            """
            UPDATE approval_queue
            SET status = ?, decision = ?, decision_notes = ?,
                decided_by = ?, decided_at = ?
            WHERE id = ?
            """,
            (decision, decision, notes, decided_by, now, item_id)
        )
        conn.commit()

        logger.info(f"[approval] decision={decision} id={item_id} by={decided_by}")
        return {**dict(row), "status": decision, "decided_at": now}
    finally:
        conn.close()


def list_pending(agent_id: str, limit: int = 20) -> list[dict]:
    """Return all pending approvals for an agent, sorted by risk (highest first)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, title, description, action_type, risk_score,
                   risk_level, status, created_at, source
            FROM approval_queue
            WHERE agent_id = ? AND status = 'pending'
            ORDER BY risk_score DESC, created_at ASC
            LIMIT ?
            """,
            (agent_id, limit)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_history(
    agent_id: str,
    status: str = None,
    limit: int = 30
) -> list[dict]:
    """Return decision history."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM approval_queue
                WHERE agent_id = ? AND status = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM approval_queue
                WHERE agent_id = ? AND status != 'pending'
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_item(item_id: str, agent_id: str) -> Optional[dict]:
    """Get full details of a single approval item."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM approval_queue WHERE id = ? AND agent_id = ?",
            (item_id, agent_id)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["action_payload"] = json.loads(d.get("action_payload", "{}"))
        return d
    finally:
        conn.close()


def get_pending_count(agent_id: str) -> int:
    """Quick count of pending approvals — used in snapshot."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM approval_queue WHERE agent_id = ? AND status = 'pending'",
            (agent_id,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
