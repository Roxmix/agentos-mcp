"""
System & Reflection Action Handlers — Sync execution for the daemon.
"""

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from loguru import logger

from config import settings


def run_reflection_analysis(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Run a full reflection analysis and persist detected patterns.
    Sync version of the analyzer (no async).

    payload keys:
      lookback_days: int
    """
    lookback_days = payload.get("lookback_days", settings.reflection_lookback_days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT action, outcome, success, created_at
            FROM reflection_logs
            WHERE agent_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (agent_id, cutoff)
        ).fetchall()

        logs = [dict(row) for row in rows]
        if not logs:
            return {"patterns_detected": 0, "message": "No logs found in lookback window"}

        # Count failures per action
        action_failures = defaultdict(list)
        for log in logs:
            if not log["success"]:
                action_failures[log["action"]].append(log)

        patterns_saved = 0
        now = datetime.now(timezone.utc).isoformat()

        for action, failures in action_failures.items():
            if len(failures) < settings.pattern_min_frequency:
                continue

            failures_sorted = sorted(failures, key=lambda x: x["created_at"])
            description = (
                f"Action '{action}' failed {len(failures)} times "
                f"in the last {lookback_days} days"
            )

            # Upsert pattern
            existing = conn.execute(
                """
                SELECT id FROM patterns
                WHERE agent_id = ? AND pattern_type = 'repeated_failure' AND description = ?
                """,
                (agent_id, description)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE patterns SET frequency = ?, last_seen = ? WHERE id = ?",
                    (len(failures), now, existing["id"])
                )
            else:
                import uuid as _uuid
                conn.execute(
                    """
                    INSERT INTO patterns
                    (id, agent_id, pattern_type, description, frequency,
                     first_seen, last_seen, related_tags, suggested_action)
                    VALUES (?, ?, 'repeated_failure', ?, ?, ?, ?, '[]', ?)
                    """,
                    (
                        str(_uuid.uuid4()), agent_id, description, len(failures),
                        failures_sorted[0]["created_at"], now,
                        f"Review approach for '{action}'"
                    )
                )
                patterns_saved += 1

        conn.commit()
        logger.info(
            f"[system_action] reflection analysis: "
            f"logs={len(logs)} patterns_saved={patterns_saved} agent={agent_id}"
        )
        return {"patterns_detected": patterns_saved, "logs_analyzed": len(logs)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_maintenance(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    General system maintenance — vacuum DB, reindex, update stats.

    payload keys:
      tasks: list of str (e.g. ["vacuum", "update_decay"])
    """
    tasks   = payload.get("tasks", ["vacuum"])
    results = {}

    conn = sqlite3.connect(db_path)
    try:
        if "vacuum" in tasks:
            conn.execute("VACUUM")
            results["vacuum"] = "ok"

        if "purge_old_insights" in tasks:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            cursor = conn.execute(
                "DELETE FROM proactive_insights WHERE seen = 1 AND created_at < ?",
                (cutoff,)
            )
            results["purge_old_insights"] = f"deleted {cursor.rowcount}"

        if "purge_old_tasks" in tasks:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
            cursor = conn.execute(
                "DELETE FROM autonomous_tasks WHERE status = 'acknowledged' AND created_at < ?",
                (cutoff,)
            )
            results["purge_old_tasks"] = f"deleted {cursor.rowcount}"

        conn.commit()
        logger.info(f"[system_action] maintenance done: {results} agent={agent_id}")
        return {"tasks_run": results}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def send_external_webhook(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Send data to an external webhook URL.

    payload keys:
      url: str
      body: dict
      secret: str (optional — added as X-AgentOS-Secret header)
    """
    import json
    import urllib.request
    import urllib.error

    url    = payload.get("url", "")
    body   = payload.get("body", {})
    secret = payload.get("secret", "")

    if not url:
        raise ValueError("url is required in payload")

    data = json.dumps({
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": body
    }).encode("utf-8")

    headers = {"Content-Type": "application/json", "User-Agent": "AgentOS/1.0"}
    if secret:
        headers["X-AgentOS-Secret"] = secret

    req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status

    logger.info(f"[system_action] webhook sent to {url} status={status}")
    return {"sent": True, "url": url, "status": status}
