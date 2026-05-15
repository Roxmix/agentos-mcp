"""
Action Executor — The missing piece that closes the loop.

Flow:
  human approves → status='approved' → Executor picks it up
               → dispatches to correct handler
               → marks executed_at
               → writes result insight

The executor runs as a scheduled daemon job every 2 minutes.
It uses optimistic locking: sets executing_at before running
to prevent double-execution if two daemon instances exist.
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Callable
from loguru import logger

from database import DB_PATH
from approval.actions import memory_actions, goal_actions, system_actions
from daemon.writer import write_insight


# ── Action Registry ───────────────────────────────────────────────────────────
# Maps action_type → handler function(db_path, agent_id, payload) → dict

ActionHandler = Callable[[str, str, dict], dict]

ACTION_REGISTRY: dict[str, ActionHandler] = {
    # Memory
    "memory.bulk_delete":        memory_actions.bulk_delete_low_importance,
    "memory.delete_low":         memory_actions.bulk_delete_low_importance,
    "memory.delete_important":   memory_actions.delete_single_memory,
    "memory.update_decay":       memory_actions.update_decay_rate,

    # Goals
    "goal.cancel":               goal_actions.cancel_goal,
    "goal.create":               goal_actions.create_goal,
    "goal.reprioritize":         goal_actions.reprioritize_goals,

    # Reflection / System
    "reflection.analyze":        system_actions.run_reflection_analysis,
    "system.maintenance":        system_actions.run_maintenance,
    "system.bulk_operation":     system_actions.run_maintenance,
    "external.webhook":          system_actions.send_external_webhook,
    "external.message":          system_actions.send_external_webhook,
}

# How long an item can stay "in execution" before we consider it stuck
EXECUTION_TIMEOUT_MINUTES = 10


# ── Executor ──────────────────────────────────────────────────────────────────

def run(db_path: str = DB_PATH):
    """
    Main executor entry point — called by the daemon scheduler.
    Fetches all approved+unexecuted items and runs them one by one.
    """
    _release_stuck_executions(db_path)

    items = _claim_approved(db_path)
    if not items:
        return

    logger.info(f"[executor] {len(items)} approved action(s) to execute")

    for item in items:
        _execute_one(db_path, item)


def _claim_approved(db_path: str) -> list[dict]:
    """
    Atomically claim approved items that haven't been executed yet.
    Sets executing_at to prevent concurrent execution.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    try:
        rows = conn.execute(
            """
            SELECT * FROM approval_queue
            WHERE status = 'approved'
              AND executed_at IS NULL
              AND (executing_at IS NULL)
            ORDER BY risk_score DESC, decided_at ASC
            LIMIT 20
            """
        ).fetchall()

        if not rows:
            return []

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE approval_queue SET executing_at = ? WHERE id IN ({placeholders})",
            [now] + ids
        )
        conn.commit()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def _execute_one(db_path: str, item: dict):
    """Execute a single approved action and record the result."""
    item_id     = item["id"]
    agent_id    = item["agent_id"]
    action_type = item["action_type"]
    title       = item["title"]

    # Parse payload
    try:
        payload = json.loads(item.get("action_payload") or "{}")
    except json.JSONDecodeError:
        payload = {}

    # Look up handler
    handler = ACTION_REGISTRY.get(action_type)
    if handler is None:
        logger.warning(f"[executor] no handler for action_type='{action_type}' — skipping")
        _mark_executed(db_path, item_id, success=False,
                       result={"error": f"No handler for {action_type}"})
        return

    logger.info(f"[executor] executing '{title}' type={action_type} agent={agent_id}")

    try:
        result = handler(db_path, agent_id, payload)
        _mark_executed(db_path, item_id, success=True, result=result)

        # Write success insight back to agent
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=_success_message(title, action_type, result),
            insight_type="autonomous_task",
            severity="info",
            source_job="executor"
        )
        logger.info(f"[executor] ✓ done: '{title}' result={result}")

    except Exception as e:
        logger.error(f"[executor] ✗ failed: '{title}' error={e}")
        _mark_executed(db_path, item_id, success=False, result={"error": str(e)})

        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"❌ فشل تنفيذ الإجراء المعتمد: \"{title}\" — "
                f"السبب: {str(e)[:200]}"
            ),
            insight_type="autonomous_task",
            severity="warning",
            source_job="executor"
        )


def _mark_executed(db_path: str, item_id: str, success: bool, result: dict):
    """Mark an item as executed and store the result."""
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        # Store result in decision_notes (reuse existing column)
        result_str = json.dumps(result)[:1000]
        new_status = "executed" if success else "failed"
        conn.execute(
            """
            UPDATE approval_queue
            SET executed_at = ?,
                executing_at = NULL,
                status = ?,
                decision_notes = COALESCE(decision_notes || ' | Result: ', 'Result: ') || ?
            WHERE id = ?
            """,
            (now, new_status, result_str, item_id)
        )
        conn.commit()
    finally:
        conn.close()


def _release_stuck_executions(db_path: str):
    """
    Release items that have been "executing" for too long
    (daemon crashed mid-execution). Resets them to approved so
    they can be retried.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=EXECUTION_TIMEOUT_MINUTES)
    ).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE approval_queue
            SET executing_at = NULL
            WHERE executing_at IS NOT NULL
              AND executing_at < ?
              AND executed_at IS NULL
            """,
            (cutoff,)
        )
        conn.commit()
        if cursor.rowcount > 0:
            logger.warning(
                f"[executor] released {cursor.rowcount} stuck execution(s)"
            )
    finally:
        conn.close()


def _success_message(title: str, action_type: str, result: dict) -> str:
    """Generate a human-readable success insight from execution result."""
    base = f"✅ تم تنفيذ الإجراء المعتمد: \"{title}\""

    detail = ""
    if "deleted" in result:
        detail = f" — تم حذف {result['deleted']} سجل."
    elif "updated" in result:
        detail = f" — تم تحديث {result['updated']} سجل."
    elif "cancelled" in result and result["cancelled"]:
        detail = f" — الهدف \"{result.get('title', '')}\" أُلغي."
    elif "created" in result and result["created"]:
        detail = f" — تم إنشاء الهدف بنجاح."
    elif "patterns_detected" in result:
        detail = f" — اكتُشف {result['patterns_detected']} نمط جديد."
    elif "sent" in result:
        detail = f" — تم الإرسال (HTTP {result.get('status', '?')})."

    return base + detail
