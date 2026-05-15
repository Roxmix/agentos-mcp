"""
Event Store — SQLite-backed inter-process event queue.

Publisher (MCP Server) writes events here.
Subscriber (Daemon) polls and processes them.

Design:
- Events are never deleted, only marked as processed (full audit trail)
- Daemon claims events atomically to prevent double-processing
- Old processed events are purged after retention period
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger

from database import DB_PATH
from events.schema import Event


# How many days to keep processed events before purging
EVENT_RETENTION_DAYS = 7


# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS event_bus (
    id          TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT 'mcp_server',
    processed   INTEGER NOT NULL DEFAULT 0,
    claimed_at  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_processed  ON event_bus(processed);
CREATE INDEX IF NOT EXISTS idx_events_agent      ON event_bus(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_type       ON event_bus(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created    ON event_bus(created_at);
"""


def init_event_store():
    """Create event_bus table if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


# ── Publisher ─────────────────────────────────────────────────────────────────

def publish(event: Event) -> str:
    """
    Write an event to the store.
    Thread-safe — uses a fresh connection per call.
    Returns the event id.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO event_bus (id, event_type, agent_id, payload, source, processed, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                event.id,
                event.event_type,
                event.agent_id,
                json.dumps(event.payload),
                event.source,
                event.created_at,
            )
        )
        conn.commit()
        logger.debug(f"[event_bus] published {event.event_type} agent={event.agent_id}")
        return event.id
    except Exception as e:
        logger.error(f"[event_bus] publish failed: {e}")
        raise
    finally:
        conn.close()


# ── Subscriber ────────────────────────────────────────────────────────────────

def claim_pending(
    batch_size: int = 50,
    event_type: Optional[str] = None,
    agent_id: Optional[str] = None
) -> list[dict]:
    """
    Atomically claim unprocessed events for processing.
    Marks them with claimed_at timestamp so parallel daemons don't double-process.
    Returns list of raw event dicts.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()

    try:
        # Build query dynamically
        conditions = ["processed = 0", "claimed_at IS NULL"]
        params: list = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        where = " AND ".join(conditions)
        params.append(batch_size)

        rows = conn.execute(
            f"""
            SELECT * FROM event_bus
            WHERE {where}
            ORDER BY created_at ASC
            LIMIT ?
            """,
            params
        ).fetchall()

        if not rows:
            return []

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE event_bus SET claimed_at = ? WHERE id IN ({placeholders})",
            [now] + ids
        )
        conn.commit()

        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "agent_id": row["agent_id"],
                "payload": json.loads(row["payload"]),
                "source": row["source"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def mark_processed(event_ids: list[str]):
    """Mark a batch of events as processed."""
    if not event_ids:
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        placeholders = ",".join("?" * len(event_ids))
        conn.execute(
            f"UPDATE event_bus SET processed = 1 WHERE id IN ({placeholders})",
            event_ids
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(event_id: str):
    """
    Release a claimed event back to the queue (processing failed).
    Resets claimed_at so it can be retried.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE event_bus SET claimed_at = NULL WHERE id = ?",
            (event_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ── Maintenance ───────────────────────────────────────────────────────────────

def purge_old_events():
    """
    Delete processed events older than EVENT_RETENTION_DAYS.
    Should be called periodically by the daemon.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=EVENT_RETENTION_DAYS)
    ).isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "DELETE FROM event_bus WHERE processed = 1 AND created_at < ?",
            (cutoff,)
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"[event_bus] purged {deleted} old events")
        return deleted
    finally:
        conn.close()


def get_stats() -> dict:
    """Return event queue statistics."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN processed = 0 AND claimed_at IS NULL THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed,
                SUM(CASE WHEN claimed_at IS NOT NULL AND processed = 0 THEN 1 ELSE 0 END) as in_flight
            FROM event_bus
            """
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
