"""
Job: Self Maintenance
Runs: every 6 hours

Proactively generates system maintenance tasks:
- Memory is growing too large → suggest compression
- Too many low-importance memories → suggest cleanup
- No reflection logs → remind agent to log actions
- No active goals → suggest goal review
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from loguru import logger

from daemon.writer import write_insight, write_autonomous_task, get_all_agent_ids, request_approval


JOB_NAME = "self_maintenance"

MAX_MEMORIES = 5000          # warn if above this
LOW_IMPORTANCE_THRESHOLD = 0.2
LOW_IMPORTANCE_RATIO = 0.4   # warn if >40% of memories are low importance
INACTIVE_REFLECTION_DAYS = 3 # warn if no logs in this many days


def run(db_path: str):
    logger.info(f"[{JOB_NAME}] Starting self-maintenance job")
    agent_ids = get_all_agent_ids(db_path)

    for agent_id in agent_ids:
        _maintain_for_agent(db_path, agent_id)

    logger.info(f"[{JOB_NAME}] Done")


def _maintain_for_agent(db_path: str, agent_id: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)

    try:
        # --- Check 1: Memory size ---
        total_memories = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ?",
            (agent_id,)
        ).fetchone()["cnt"]

        # --- Check 2: Too many low-importance memories ---
        # (computed early because Check 1's request_approval needs it)
        low_importance_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ? AND importance < ?",
            (agent_id, LOW_IMPORTANCE_THRESHOLD)
        ).fetchone()["cnt"]

        if total_memories > MAX_MEMORIES:
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight=(
                    f"🧠 الذاكرة تحتوي على {total_memories:,} سجل — "
                    f"يُنصح بتنظيف الذكريات منخفضة الأهمية."
                ),
                insight_type="autonomous_task",
                severity="warning",
                source_job=JOB_NAME
            )
            # High-risk: request approval instead of executing directly
            request_approval(
                db_path=db_path,
                agent_id=agent_id,
                title=f"حذف الذكريات منخفضة الأهمية ({total_memories:,} سجل)",
                description=(
                    f"الذاكرة وصلت إلى {total_memories:,} سجل. "
                    f"يُقترح حذف السجلات التي أهميتها أقل من {LOW_IMPORTANCE_THRESHOLD} "
                    f"ولم تُستخدم منذ 30 يوماً ({low_importance_count:,} سجل مؤهل)."
                ),
                action_type="memory.bulk_delete",
                action_payload={
                    "min_importance_threshold": LOW_IMPORTANCE_THRESHOLD,
                    "estimated_count": low_importance_count
                },
                source_job=JOB_NAME
            )

        if total_memories > 0:
            ratio = low_importance_count / total_memories
            if ratio > LOW_IMPORTANCE_RATIO:
                write_autonomous_task(
                    db_path=db_path,
                    agent_id=agent_id,
                    title="مراجعة وحذف الذكريات منخفضة القيمة",
                    reason=(
                        f"{ratio:.0%} من الذكريات ({low_importance_count:,} سجل) "
                        "أهميتها منخفضة جداً."
                    ),
                    priority=0.4,
                    source_job=JOB_NAME
                )

        # --- Check 3: No reflection logs recently ---
        cutoff = (now - timedelta(days=INACTIVE_REFLECTION_DAYS)).isoformat()
        recent_logs = conn.execute(
            "SELECT COUNT(*) as cnt FROM reflection_logs WHERE agent_id = ? AND created_at >= ?",
            (agent_id, cutoff)
        ).fetchone()["cnt"]

        if recent_logs == 0 and total_memories > 0:
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight=(
                    f"📋 لا توجد سجلات تأمل في آخر {INACTIVE_REFLECTION_DAYS} أيام — "
                    "الوكيل لا يسجّل أفعاله. التأمل الذاتي معطّل فعلياً."
                ),
                insight_type="autonomous_task",
                severity="warning",
                source_job=JOB_NAME
            )

        # --- Check 4: No active goals ---
        active_goals = conn.execute(
            "SELECT COUNT(*) as cnt FROM goals WHERE agent_id = ? AND status = 'active'",
            (agent_id,)
        ).fetchone()["cnt"]

        if active_goals == 0 and total_memories > 10:
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight="🎯 لا توجد أهداف نشطة — الوكيل يعمل بدون توجيه واضح.",
                insight_type="autonomous_task",
                severity="info",
                source_job=JOB_NAME
            )
            write_autonomous_task(
                db_path=db_path,
                agent_id=agent_id,
                title="تحديد أهداف جديدة",
                reason="لا توجد أهداف نشطة حالياً.",
                priority=0.5,
                source_job=JOB_NAME
            )

        logger.info(
            f"[{JOB_NAME}] agent={agent_id}: "
            f"memories={total_memories}, active_goals={active_goals}, "
            f"recent_logs={recent_logs}"
        )

    finally:
        conn.close()
