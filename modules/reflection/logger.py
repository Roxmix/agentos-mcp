"""
Reflection Module - Log agent actions and outcomes
"""

import uuid
from typing import Optional, List, Dict, Any

from database import get_db, now_utc, serialize_tags, parse_tags, row_to_dict


async def log_reflection(
    agent_id: str,
    action: str,
    outcome: str,
    success: bool,
    context: str = "",
    goal_id: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Log an action and its outcome for later reflection analysis."""
    if tags is None:
        tags = []

    log_id = str(uuid.uuid4())
    created_at = now_utc()

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO reflection_logs 
            (id, agent_id, action, outcome, success, context, tags, goal_id, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, agent_id, action, outcome, 1 if success else 0, context,
             serialize_tags(tags), goal_id, created_at, "{}")
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "id": log_id,
        "agent_id": agent_id,
        "action": action,
        "outcome": outcome,
        "success": success,
        "context": context,
        "tags": tags,
        "goal_id": goal_id,
        "created_at": created_at,
        "metadata": {}
    }
