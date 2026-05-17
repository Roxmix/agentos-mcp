"""
Daemon Writer — shared helpers for all jobs to write
insights and autonomous tasks into the database.
"""

import uuid
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def write_insight(
    db_path: str,
    agent_id: str,
    insight: str,
    insight_type: str,
    severity: str = "info",
    source_job: str = ""
) -> str:
    """
    Insert a proactive insight into the database.
    Deduplicates: if identical insight text already exists unseen, skip.
    Returns the insight id.
    """
    conn = _get_conn(db_path)
    try:
        # Deduplicate unseen insights with identical text
        row = conn.execute(
            """
            SELECT id FROM proactive_insights
            WHERE agent_id = ? AND insight = ? AND seen = 0
            """,
            (agent_id, insight)
        ).fetchone()

        if row:
            return row["id"]

        insight_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO proactive_insights
            (id, agent_id, insight, insight_type, severity, seen, created_at, source_job)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (insight_id, agent_id, insight, insight_type, severity, _now(), source_job)
        )
        conn.commit()
        return insight_id
    finally:
        conn.close()


def write_autonomous_task(
    db_path: str,
    agent_id: str,
    title: str,
    reason: str,
    priority: float = 0.5,
    source_job: str = ""
) -> str:
    """
    Insert an autonomous task into the database.
    Deduplicates: if identical title already pending, skip.
    Returns the task id.
    """
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            """
            SELECT id FROM autonomous_tasks
            WHERE agent_id = ? AND title = ? AND status = 'pending'
            """,
            (agent_id, title)
        ).fetchone()

        if row:
            return row["id"]

        task_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO autonomous_tasks
            (id, agent_id, title, reason, status, priority, created_at, source_job)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (task_id, agent_id, title, reason, priority, _now(), source_job)
        )
        conn.commit()
        return task_id
    finally:
        conn.close()


def update_heartbeat(db_path: str, agent_id: str, jobs_run: int):
    """Update daemon heartbeat for this agent."""
    conn = _get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO daemon_heartbeat (agent_id, last_seen, jobs_run, status)
            VALUES (?, ?, ?, 'running')
            ON CONFLICT(agent_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                jobs_run = daemon_heartbeat.jobs_run + excluded.jobs_run,
                status = 'running'
            """,
            (agent_id, _now(), jobs_run)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_agent_ids(db_path: str) -> list[str]:
    """Return all unique agent_ids found across all tables, plus the primary agent."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import settings

    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT agent_id FROM memories
            UNION
            SELECT DISTINCT agent_id FROM goals
            UNION
            SELECT DISTINCT agent_id FROM reflection_logs
            """
        ).fetchall()
        agent_ids = [row["agent_id"] for row in rows]
    finally:
        conn.close()

    # Always include the primary agent
    primary = settings.primary_agent_id
    if primary not in agent_ids:
        agent_ids.insert(0, primary)

    return agent_ids


def request_approval(
    db_path: str,
    agent_id: str,
    title: str,
    description: str,
    action_type: str,
    action_payload: dict = None,
    source_job: str = ""
) -> dict:
    """
    Submit a high-risk decision to the approval queue instead of executing it.
    Sends a webhook notification automatically.
    Returns the queued item.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from approval.queue import enqueue, calculate_risk
    from approval.webhook import notify

    if action_payload is None:
        action_payload = {}

    risk_score, risk_level = calculate_risk(action_type, action_payload)

    item = enqueue(
        agent_id=agent_id,
        title=title,
        description=description,
        action_type=action_type,
        action_payload=action_payload,
        risk_score=risk_score,
        risk_level=risk_level,
        source=source_job
    )

    # Notify external webhook
    notify(item)

    return item
