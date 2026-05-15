"""
Job: Reflection Analyzer
Runs: every 30 minutes

Analyzes recent reflection logs to detect failure patterns
and surface actionable insights automatically.
"""

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from loguru import logger

from daemon.writer import write_insight, write_autonomous_task, get_all_agent_ids
from config import settings


JOB_NAME = "reflection_analyzer"


def run(db_path: str):
    logger.info(f"[{JOB_NAME}] Starting reflection analysis job")
    agent_ids = get_all_agent_ids(db_path)

    for agent_id in agent_ids:
        _analyze_for_agent(db_path, agent_id)

    logger.info(f"[{JOB_NAME}] Done")


def _analyze_for_agent(db_path: str, agent_id: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=settings.reflection_lookback_days)).isoformat()

    try:
        rows = conn.execute(
            """
            SELECT action, outcome, success, created_at
            FROM reflection_logs
            WHERE agent_id = ? AND created_at >= ?
            """,
            (agent_id, cutoff)
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < settings.pattern_min_frequency:
        return

    logs = [dict(row) for row in rows]
    total = len(logs)
    successes = sum(1 for log in logs if log["success"])
    failures = total - successes
    success_rate = successes / total if total > 0 else 0.0

    # --- Insight 1: Overall performance drop ---
    if success_rate < 0.4 and total >= 5:
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"📉 معدل النجاح انخفض إلى {success_rate:.0%} "
                f"في آخر {settings.reflection_lookback_days} أيام "
                f"({failures} فشل من أصل {total} محاولة)."
            ),
            insight_type="pattern",
            severity="warning",
            source_job=JOB_NAME
        )
        write_autonomous_task(
            db_path=db_path,
            agent_id=agent_id,
            title="تحليل أسباب انخفاض معدل النجاح",
            reason=f"معدل النجاح {success_rate:.0%} — أقل من الحد المقبول.",
            priority=0.8,
            source_job=JOB_NAME
        )

    # --- Insight 2: Repeated failure on same action ---
    action_failures = defaultdict(int)
    for log in logs:
        if not log["success"]:
            action_failures[log["action"]] += 1

    for action, count in action_failures.items():
        if count >= settings.pattern_min_frequency:
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight=(
                    f"🔁 الإجراء \"{action}\" فشل {count} مرات متكررة — "
                    "قد يحتاج إلى نهج مختلف."
                ),
                insight_type="pattern",
                severity="warning",
                source_job=JOB_NAME
            )
            write_autonomous_task(
                db_path=db_path,
                agent_id=agent_id,
                title=f"مراجعة نهج: {action}",
                reason=f"فشل {count} مرات متكررة في آخر {settings.reflection_lookback_days} أيام.",
                priority=0.7,
                source_job=JOB_NAME
            )

    # --- Insight 3: What's working well ---
    action_successes = defaultdict(int)
    for log in logs:
        if log["success"]:
            action_successes[log["action"]] += 1

    best_actions = sorted(action_successes.items(), key=lambda x: x[1], reverse=True)[:2]
    for action, count in best_actions:
        if count >= settings.pattern_min_frequency:
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight=(
                    f"✅ الإجراء \"{action}\" ينجح باستمرار ({count} مرة) — "
                    "استمر في استخدام هذا النهج."
                ),
                insight_type="pattern",
                severity="info",
                source_job=JOB_NAME
            )

    logger.info(
        f"[{JOB_NAME}] agent={agent_id}: "
        f"total={total}, success_rate={success_rate:.0%}, "
        f"repeated_failures={len([a for a, c in action_failures.items() if c >= settings.pattern_min_frequency])}"
    )
