"""
Goal Action Handlers — Sync execution for the daemon.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from loguru import logger


def cancel_goal(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Cancel an active goal.

    payload keys:
      goal_id: str
      reason: str (optional)
    """
    goal_id = payload.get("goal_id")
    reason  = payload.get("reason", "Cancelled by approved daemon action")

    if not goal_id:
        raise ValueError("goal_id is required in payload")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    try:
        row = conn.execute(
            "SELECT id, title, status FROM goals WHERE id = ? AND agent_id = ?",
            (goal_id, agent_id)
        ).fetchone()

        if not row:
            return {"cancelled": False, "message": "Goal not found"}
        if row["status"] not in ("active", "paused"):
            return {"cancelled": False, "message": f"Goal is already {row['status']}"}

        conn.execute(
            """
            UPDATE goals
            SET status = 'abandoned', completion_notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (reason, now, goal_id)
        )
        conn.commit()
        logger.info(f"[goal_action] cancelled goal={goal_id} title='{row['title']}'")
        return {"cancelled": True, "goal_id": goal_id, "title": row["title"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_goal(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Create a new goal autonomously (post-approval).

    payload keys:
      title: str
      description: str
      priority: float
      urgency: float
      deadline: str | None
    """
    now     = datetime.now(timezone.utc).isoformat()
    goal_id = str(uuid.uuid4())

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO goals
            (id, agent_id, title, description, priority, urgency,
             status, progress, tags, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, 'active', 0.0, '[]', ?, ?, '{}')
            """,
            (
                goal_id, agent_id,
                payload.get("title", "Auto-generated goal"),
                payload.get("description", ""),
                payload.get("priority", 0.5),
                payload.get("urgency", 0.5),
                now, now
            )
        )
        conn.commit()
        logger.info(f"[goal_action] created goal={goal_id} title='{payload.get('title')}'")
        return {"created": True, "goal_id": goal_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reprioritize_goals(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Batch-update priorities for a list of goals.

    payload keys:
      updates: list of {goal_id: str, priority: float, urgency: float}
    """
    updates = payload.get("updates", [])
    if not updates:
        return {"updated": 0, "message": "No updates provided"}

    now  = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    updated = 0
    try:
        for upd in updates:
            goal_id  = upd.get("goal_id")
            priority = upd.get("priority")
            urgency  = upd.get("urgency")
            if not goal_id:
                continue
            cursor = conn.execute(
                """
                UPDATE goals
                SET priority = COALESCE(?, priority),
                    urgency  = COALESCE(?, urgency),
                    updated_at = ?
                WHERE id = ? AND agent_id = ? AND status = 'active'
                """,
                (priority, urgency, now, goal_id, agent_id)
            )
            updated += cursor.rowcount
        conn.commit()
        logger.info(f"[goal_action] reprioritized {updated} goals for agent={agent_id}")
        return {"updated": updated}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
