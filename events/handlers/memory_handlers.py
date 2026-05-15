"""
Memory Event Handlers — Daemon side.
Reacts to memory events in real-time.
"""

from loguru import logger
from daemon.writer import write_insight


def on_memory_stored(event: dict, db_path: str):
    """
    Triggered immediately when the agent stores a new memory.
    Checks if this is a high-importance memory and flags it.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    importance = payload.get("importance", 0.5)
    memory_type = payload.get("memory_type", "episodic")
    tags = payload.get("tags", [])

    logger.debug(
        f"[memory_handler] memory.stored agent={agent_id} "
        f"type={memory_type} importance={importance}"
    )

    # Flag critical memories immediately
    if importance >= 0.9:
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"🔴 ذاكرة بأهمية قصوى ({importance}) تم تخزينها — "
                f"النوع: {memory_type}, الوسوم: {', '.join(tags) or 'لا يوجد'}."
            ),
            insight_type="memory_conflict",
            severity="info",
            source_job="event:memory.stored"
        )


def on_memory_deleted(event: dict, db_path: str):
    """
    Triggered when a memory is deleted.
    Logs for audit purposes.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    memory_id = payload.get("memory_id")

    logger.info(
        f"[memory_handler] memory.deleted agent={agent_id} id={memory_id}"
    )
