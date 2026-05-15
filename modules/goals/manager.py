"""
Goals Module - CRUD for goals
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from database import get_db, now_utc, serialize_tags, parse_tags, row_to_dict
from modules.goals.prioritizer import calculate_composite_score


async def add_goal(
    agent_id: str,
    title: str,
    description: str,
    priority: float = 0.5,
    urgency: float = 0.5,
    deadline: Optional[str] = None,
    parent_goal_id: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Add a new goal for the agent."""
    if tags is None:
        tags = []

    goal_id = str(uuid.uuid4())
    created_at = now_utc()

    # Clamp values
    priority = max(0.0, min(1.0, priority))
    urgency = max(0.0, min(1.0, urgency))

    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO goals 
            (id, agent_id, title, description, priority, urgency, status, progress,
             parent_goal_id, tags, deadline, created_at, updated_at, completion_notes, retry_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (goal_id, agent_id, title, description, priority, urgency, "active", 0.0,
             parent_goal_id, serialize_tags(tags), deadline, created_at, created_at, None, 0, "{}")
        )
        await db.commit()
    finally:
        await db.close()

    goal_data = {
        "id": goal_id,
        "agent_id": agent_id,
        "title": title,
        "description": description,
        "priority": priority,
        "urgency": urgency,
        "status": "active",
        "progress": 0.0,
        "parent_goal_id": parent_goal_id,
        "tags": tags,
        "deadline": deadline,
        "created_at": created_at,
        "updated_at": created_at,
        "completion_notes": None,
        "retry_count": 0,
        "metadata": {}
    }

    goal_data["composite_score"] = calculate_composite_score(goal_data)
    return goal_data


async def get_active_goals(agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return active goals sorted by composite priority score."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM goals 
            WHERE agent_id = ? AND status = 'active'
            ORDER BY priority DESC, urgency DESC
            """,
            (agent_id,)
        )
        rows = await cursor.fetchall()

        goals = []
        for row in rows:
            goal = row_to_dict(row)
            goal["tags"] = parse_tags(goal.get("tags", "[]"))
            goal["metadata"] = {}
            goal["composite_score"] = calculate_composite_score(goal)
            goals.append(goal)

        # Sort by composite score
        goals.sort(key=lambda g: g["composite_score"], reverse=True)
        return goals[:limit]
    finally:
        await db.close()


async def update_goal_progress(
    agent_id: str,
    goal_id: str,
    progress: float,
    notes: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Update progress on a goal. Automatically marks as completed if progress >= 1.0"""
    progress = max(0.0, min(1.0, progress))
    updated_at = now_utc()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT agent_id FROM goals WHERE id = ?",
            (goal_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["agent_id"] != agent_id:
            return None

        status = "completed" if progress >= 1.0 else "active"

        await db.execute(
            """
            UPDATE goals 
            SET progress = ?, status = ?, updated_at = ?, completion_notes = ?
            WHERE id = ?
            """,
            (progress, status, updated_at, notes, goal_id)
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
        row = await cursor.fetchone()
        goal = row_to_dict(row)
        goal["tags"] = parse_tags(goal.get("tags", "[]"))
        goal["metadata"] = {}
        goal["composite_score"] = calculate_composite_score(goal)
        return goal
    finally:
        await db.close()


async def update_goal_status(
    agent_id: str,
    goal_id: str,
    status: str,
    notes: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Change the status of a goal."""
    if status not in ("active", "paused", "completed", "abandoned"):
        return None

    updated_at = now_utc()

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT agent_id FROM goals WHERE id = ?",
            (goal_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["agent_id"] != agent_id:
            return None

        await db.execute(
            """
            UPDATE goals 
            SET status = ?, updated_at = ?, completion_notes = ?
            WHERE id = ?
            """,
            (status, updated_at, notes, goal_id)
        )
        await db.commit()

        cursor = await db.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
        row = await cursor.fetchone()
        goal = row_to_dict(row)
        goal["tags"] = parse_tags(goal.get("tags", "[]"))
        goal["metadata"] = {}
        goal["composite_score"] = calculate_composite_score(goal)
        return goal
    finally:
        await db.close()


async def list_goals(
    agent_id: str,
    status: str = "active",
    limit: int = 20
) -> List[Dict[str, Any]]:
    """List goals filtered by status. Use status='all' for no filter."""
    db = await get_db()
    try:
        if status == "all":
            cursor = await db.execute(
                """
                SELECT * FROM goals
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, limit)
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM goals
                WHERE agent_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, status, limit)
            )
        rows = await cursor.fetchall()

        goals = []
        for row in rows:
            goal = row_to_dict(row)
            goal["tags"] = parse_tags(goal.get("tags", "[]"))
            goal["metadata"] = {}
            goal["composite_score"] = calculate_composite_score(goal)
            goals.append(goal)

        return goals
    finally:
        await db.close()
