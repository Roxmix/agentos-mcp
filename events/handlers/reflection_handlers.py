"""
Reflection Event Handlers — Daemon side.
The most important handlers — react to failures immediately
instead of waiting for the scheduled 30-min analysis job.
"""

import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from loguru import logger

from daemon.writer import write_insight, write_autonomous_task
from config import settings


def on_reflection_logged(event: dict, db_path: str):
    """
    Triggered on any reflection log (success or failure).
    Tracks action history for quick pattern detection.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    action = payload.get("action", "")
    success = payload.get("success", True)

    logger.debug(
        f"[reflection_handler] reflection.logged agent={agent_id} "
        f"action='{action}' success={success}"
    )


def on_reflection_failed(event: dict, db_path: str):
    """
    Triggered IMMEDIATELY when an action fails.
    Checks recent failure count and raises alert if threshold is crossed.
    This is the key reactive behavior — no need to wait 30 minutes.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    action = payload.get("action", "")
    tags = payload.get("tags", [])

    logger.debug(
        f"[reflection_handler] reflection.failed agent={agent_id} action='{action}'"
    )

    # Count how many times this exact action failed recently
    recent_failures = _count_recent_failures(
        db_path=db_path,
        agent_id=agent_id,
        action=action,
        lookback_hours=24
    )

    if recent_failures >= settings.pattern_min_frequency:
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"🔴 تحذير فوري: الإجراء \"{action}\" فشل "
                f"{recent_failures} مرات خلال آخر 24 ساعة. "
                "يبدو أن هناك مشكلة متكررة تحتاج معالجة."
            ),
            insight_type="pattern",
            severity="critical",
            source_job="event:reflection.failed"
        )
        write_autonomous_task(
            db_path=db_path,
            agent_id=agent_id,
            title=f"تحقيق فوري: فشل متكرر في \"{action}\"",
            reason=(
                f"فشل {recent_failures} مرات في 24 ساعة — "
                "يحتاج تدخل فوري."
            ),
            priority=0.9,
            source_job="event:reflection.failed"
        )
    elif recent_failures == 2:
        # Early warning at 2 failures
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"⚠️ الإجراء \"{action}\" فشل مرتين اليوم — "
                "تابع الوضع."
            ),
            insight_type="pattern",
            severity="warning",
            source_job="event:reflection.failed"
        )


def on_pattern_detected(event: dict, db_path: str):
    """
    Triggered when a pattern is detected (usually by the scheduled analyzer).
    Creates an autonomous task if the pattern is a repeated failure.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    pattern_type = payload.get("pattern_type", "")
    description = payload.get("description", "")
    frequency = payload.get("frequency", 0)

    logger.debug(
        f"[reflection_handler] pattern.detected agent={agent_id} "
        f"type={pattern_type} freq={frequency}"
    )

    if pattern_type == "repeated_failure" and frequency >= 5:
        write_autonomous_task(
            db_path=db_path,
            agent_id=agent_id,
            title=f"معالجة نمط فشل متكرر (تكرر {frequency} مرات)",
            reason=description,
            priority=0.85,
            source_job="event:pattern.detected"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_recent_failures(
    db_path: str,
    agent_id: str,
    action: str,
    lookback_hours: int = 24
) -> int:
    """Count how many times an action failed in the last N hours."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    ).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as cnt
            FROM reflection_logs
            WHERE agent_id = ?
              AND action = ?
              AND success = 0
              AND created_at >= ?
            """,
            (agent_id, action, cutoff)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
