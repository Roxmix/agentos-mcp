"""
Memory Action Handlers — Sync execution for the daemon.

These are the actual implementations that run after a human approves
a memory-related decision.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from loguru import logger


def bulk_delete_low_importance(
    db_path: str,
    agent_id: str,
    payload: dict
) -> dict:
    """
    Delete memories below importance threshold that haven't been
    accessed in a long time.

    payload keys:
      min_importance_threshold: float (e.g. 0.2)
      estimated_count: int (informational only)
    """
    threshold   = payload.get("min_importance_threshold", 0.2)
    cutoff_days = payload.get("cutoff_days", 30)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=cutoff_days)).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Fetch IDs to delete — never delete procedural memory automatically
        rows = conn.execute(
            """
            SELECT id FROM memories
            WHERE agent_id = ?
              AND importance < ?
              AND memory_type != 'procedural'
              AND (last_accessed < ? OR last_accessed IS NULL)
            LIMIT 2000
            """,
            (agent_id, threshold, cutoff_date)
        ).fetchall()

        if not rows:
            return {"deleted": 0, "message": "No eligible memories found"}

        ids = [row["id"] for row in rows]

        # Delete from SQLite
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            ids
        )
        conn.commit()

        # Delete from ChromaDB (best-effort — don't crash if it fails)
        try:
            import chromadb
            from config import settings
            client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            col = client.get_or_create_collection(settings.chroma_collection_name)
            # ChromaDB accepts max 166 IDs per delete call
            batch = 100
            for i in range(0, len(ids), batch):
                col.delete(ids=ids[i:i+batch])
        except Exception as e:
            logger.warning(f"[memory_action] ChromaDB cleanup partial: {e}")

        logger.info(
            f"[memory_action] bulk_delete: deleted {len(ids)} memories "
            f"for agent={agent_id}"
        )
        return {"deleted": len(ids), "message": f"Deleted {len(ids)} low-importance memories"}

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_single_memory(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Delete a single specific memory by ID.

    payload keys:
      memory_id: str
    """
    memory_id = payload.get("memory_id")
    if not memory_id:
        raise ValueError("memory_id is required in payload")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id FROM memories WHERE id = ? AND agent_id = ?",
            (memory_id, agent_id)
        ).fetchone()

        if not row:
            return {"deleted": 0, "message": "Memory not found or access denied"}

        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()

        try:
            import chromadb
            from config import settings
            client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            col = client.get_or_create_collection(settings.chroma_collection_name)
            col.delete(ids=[memory_id])
        except Exception as e:
            logger.warning(f"[memory_action] ChromaDB delete failed: {e}")

        return {"deleted": 1, "memory_id": memory_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_decay_rate(db_path: str, agent_id: str, payload: dict) -> dict:
    """
    Apply a one-time decay update to all memories of an agent.

    payload keys:
      decay_amount: float (subtracted from decay_score)
    """
    amount = payload.get("decay_amount", 0.05)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE memories
            SET decay_score = MAX(0.0, decay_score - ?)
            WHERE agent_id = ? AND memory_type != 'procedural'
            """,
            (amount, agent_id)
        )
        conn.commit()
        return {"updated": cursor.rowcount, "decay_amount": amount}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
