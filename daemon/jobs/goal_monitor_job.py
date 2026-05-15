"""
Job: Goal Monitor
Runs: every 60 minutes

Monitors active goals for:
- Approaching deadlines
- Stalled progress (no update in N days)
- Abandoned goals with high priority
Generates insights and autonomous tasks accordingly.
"""

import sqlite3
import json
from datetime import datetime, timezone, timedelta
from loguru import logger

from daemon.writer import write_insight, write_autonomous_task, get_all_agent_ids


JOB_NAME = "goal_monitor"
STALL_DAYS = 3          # days with no progress = stalled
DEADLINE_WARN_DAYS = 2  # warn when deadline is within this many days


def run(db_path: str):
    logger.info(f"[{JOB_NAME}] Starting goal monitor job")
    agent_ids = get_all_agent_ids(db_path)

    for agent_id in agent_ids:
        _monitor_for_agent(db_path, agent_id)

    logger.info(f"[{JOB_NAME}] Done")


def _monitor_for_agent(db_path: str, agent_id: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)

    try:
        rows = conn.execute(
            "SELECT * FROM goals WHERE agent_id = ? AND status = 'active'",
            (agent_id,)
        ).fetchall()

        for row in rows:
            goal = dict(row)
            title = goal["title"]
            priority = goal.get("priority", 0.5)
            progress = goal.get("progress", 0.0)

            # --- Check 1: Approaching deadline ---
            if goal.get("deadline"):
                try:
                    deadline = datetime.fromisoformat(goal["deadline"])
                    if deadline.tzinfo is None:
                        deadline = deadline.replace(tzinfo=timezone.utc)
                    days_left = (deadline - now).days

                    if days_left <= 0:
                        write_insight(
                            db_path=db_path,
                            agent_id=agent_id,
                            insight=f"⚠️ الهدف \"{title}\" تجاوز موعد نهايته منذ {abs(days_left)} يوم.",
                            insight_type="goal_alert",
                            severity="critical",
                            source_job=JOB_NAME
                        )
                        write_autonomous_task(
                            db_path=db_path,
                            agent_id=agent_id,
                            title=f"مراجعة الهدف المتأخر: {title}",
                            reason=f"الهدف تجاوز موعده — قرر: استمرار، تعديل، أو إغلاق.",
                            priority=min(1.0, priority + 0.3),
                            source_job=JOB_NAME
                        )
                    elif days_left <= DEADLINE_WARN_DAYS:
                        write_insight(
                            db_path=db_path,
                            agent_id=agent_id,
                            insight=(
                                f"⏰ الهدف \"{title}\" يقترب من موعد نهايته — "
                                f"متبقٍ {days_left} يوم، التقدم الحالي {progress:.0%}."
                            ),
                            insight_type="goal_alert",
                            severity="warning",
                            source_job=JOB_NAME
                        )
                except Exception as e:
                    logger.warning(f"[{JOB_NAME}] Could not parse deadline for goal {goal['id']}: {e}")

            # --- Check 2: Stalled progress ---
            updated_at_str = goal.get("updated_at") or goal.get("created_at")
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                days_stalled = (now - updated_at).days

                if days_stalled >= STALL_DAYS and progress < 1.0:
                    write_insight(
                        db_path=db_path,
                        agent_id=agent_id,
                        insight=(
                            f"📌 الهدف \"{title}\" متوقف منذ {days_stalled} أيام "
                            f"(التقدم: {progress:.0%})."
                        ),
                        insight_type="goal_alert",
                        severity="warning" if priority >= 0.7 else "info",
                        source_job=JOB_NAME
                    )
                    if priority >= 0.7:
                        write_autonomous_task(
                            db_path=db_path,
                            agent_id=agent_id,
                            title=f"استئناف الهدف المتوقف: {title}",
                            reason=f"الهدف لم يتقدم منذ {days_stalled} أيام وأولويته عالية.",
                            priority=priority,
                            source_job=JOB_NAME
                        )
            except Exception as e:
                logger.warning(f"[{JOB_NAME}] Could not parse updated_at for goal {goal['id']}: {e}")

    finally:
        conn.close()
