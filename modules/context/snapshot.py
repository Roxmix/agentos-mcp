"""
Context Module - Unified cognitive state snapshot
Includes proactive insights and autonomous tasks from the daemon.
"""

import sqlite3
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from database import get_db, parse_tags, row_to_dict, DB_PATH
from modules.memory.retriever import list_memories
from modules.goals.manager import list_goals
from modules.reflection.analyzer import get_patterns


async def build_snapshot(
    agent_id: str,
    include_memories: int = 5,
    include_goals: int = 5,
    include_patterns: int = 3
) -> Dict[str, Any]:
    """
    Build a unified snapshot of the agent's current cognitive state.
    Marks returned insights as seen.
    """
    # Fetch top memories (most recent)
    top_memories = await list_memories(
        agent_id=agent_id,
        limit=include_memories
    )

    # Fetch active goals sorted by priority
    active_goals = await list_goals(
        agent_id=agent_id,
        status="active",
        limit=include_goals
    )

    # Fetch recent patterns
    recent_patterns = await get_patterns(
        agent_id=agent_id
    )
    recent_patterns = recent_patterns[:include_patterns]

    # Fetch performance stats
    db = await get_db()
    try:
        total_memories_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ?",
            (agent_id,)
        )
        total_memories = (await total_memories_row.fetchone())["cnt"]

        total_goals_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM goals WHERE agent_id = ?",
            (agent_id,)
        )
        total_goals = (await total_goals_row.fetchone())["cnt"]

        completed_goals_row = await db.execute(
            "SELECT COUNT(*) as cnt FROM goals WHERE agent_id = ? AND status = 'completed'",
            (agent_id,)
        )
        completed_goals = (await completed_goals_row.fetchone())["cnt"]

        # 7-day success rate
        logs_row = await db.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes
            FROM reflection_logs
            WHERE agent_id = ?
              AND created_at >= datetime('now', '-7 days')
            """,
            (agent_id,)
        )
        log_stats = await logs_row.fetchone()
        total_logs = log_stats["total"] or 0
        successes = log_stats["successes"] or 0
        success_rate = round(successes / total_logs, 2) if total_logs > 0 else 0.0

    finally:
        await db.close()

    # Fetch unread proactive insights from daemon (run in thread to avoid blocking)
    proactive_insights = await asyncio.to_thread(
        _fetch_and_mark_insights_sync, agent_id, limit=10
    )

    # Fetch pending autonomous tasks from daemon
    autonomous_tasks = await asyncio.to_thread(
        _fetch_and_acknowledge_tasks_sync, agent_id, limit=5
    )

    # Daemon liveness
    daemon_status = await asyncio.to_thread(
        _get_daemon_status_sync
    )

    return {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "top_memories": top_memories,
        "active_goals": active_goals,
        "recent_patterns": recent_patterns,
        "proactive_insights": proactive_insights,
        "autonomous_tasks": autonomous_tasks,
        "daemon_status": daemon_status,
        "performance_summary": {
            "last_7_days_success_rate": success_rate,
            "total_memories": total_memories,
            "total_goals": total_goals,
            "completed_goals": completed_goals,
        }
    }


def _fetch_and_mark_insights_sync(agent_id: str, limit: int = 10) -> list:
    """Fetch unseen insights and mark them as seen. (sync — run in thread)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM proactive_insights
            WHERE agent_id = ? AND seen = 0
            ORDER BY
                CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                created_at DESC
            LIMIT ?
            """,
            (agent_id, limit)
        ).fetchall()

        insights = []
        ids_to_mark = []
        for row in rows:
            d = dict(row)
            insights.append({
                "id": d["id"],
                "insight": d["insight"],
                "type": d["insight_type"],
                "severity": d["severity"],
                "created_at": d["created_at"],
                "source": d["source_job"],
            })
            ids_to_mark.append(d["id"])

        # Mark as seen
        if ids_to_mark:
            placeholders = ",".join("?" * len(ids_to_mark))
            conn.execute(
                f"UPDATE proactive_insights SET seen = 1 WHERE id IN ({placeholders})",
                ids_to_mark
            )
            conn.commit()

        return insights
    finally:
        conn.close()


def _fetch_and_acknowledge_tasks_sync(agent_id: str, limit: int = 5) -> list:
    """Fetch pending autonomous tasks and mark them as acknowledged. (sync — run in thread)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM autonomous_tasks
            WHERE agent_id = ? AND status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?
            """,
            (agent_id, limit)
        ).fetchall()

        tasks = []
        ids_to_ack = []
        for row in rows:
            d = dict(row)
            tasks.append({
                "id": d["id"],
                "title": d["title"],
                "reason": d["reason"],
                "priority": d["priority"],
                "created_at": d["created_at"],
                "source": d["source_job"],
            })
            ids_to_ack.append(d["id"])

        if ids_to_ack:
            placeholders = ",".join("?" * len(ids_to_ack))
            conn.execute(
                f"UPDATE autonomous_tasks SET status = 'acknowledged' WHERE id IN ({placeholders})",
                ids_to_ack
            )
            conn.commit()

        return tasks
    finally:
        conn.close()


def _get_daemon_status_sync() -> dict:
    """Check if the daemon is alive based on its last heartbeat. (sync — run in thread)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM daemon_heartbeat WHERE agent_id = '__daemon__'"
        ).fetchone()

        if not row:
            return {"alive": False, "last_seen": None, "status": "never_started"}

        d = dict(row)
        try:
            last_seen = datetime.fromisoformat(d["last_seen"])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            minutes_ago = (datetime.now(timezone.utc) - last_seen).seconds // 60
            alive = minutes_ago < 3  # dead if no heartbeat in 3 min
        except Exception:
            alive = False
            minutes_ago = None

        return {
            "alive": alive,
            "last_seen": d["last_seen"],
            "status": d["status"],
            "minutes_since_heartbeat": minutes_ago,
        }
    finally:
        conn.close()
