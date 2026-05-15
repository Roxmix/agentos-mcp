"""
Reflection Module - Detect patterns from logs
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from database import get_db, now_utc, serialize_tags, parse_tags, row_to_dict
from config import settings


async def _upsert_pattern(
    agent_id: str,
    pattern_type: str,
    description: str,
    frequency: int,
    first_seen: str,
    last_seen: str,
    related_tags: List[str],
    suggested_action: str
) -> Dict[str, Any]:
    """
    Insert a new pattern or update frequency/last_seen if it already exists.
    Deduplication key: (agent_id, pattern_type, description)
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, frequency FROM patterns
            WHERE agent_id = ? AND pattern_type = ? AND description = ?
            """,
            (agent_id, pattern_type, description)
        )
        existing = await cursor.fetchone()

        if existing:
            # Update existing pattern
            await db.execute(
                """
                UPDATE patterns
                SET frequency = ?, last_seen = ?, suggested_action = ?
                WHERE id = ?
                """,
                (frequency, last_seen, suggested_action, existing["id"])
            )
            await db.commit()
            return {"id": existing["id"], "updated": True}
        else:
            # Insert new pattern
            pattern_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO patterns
                (id, agent_id, pattern_type, description, frequency,
                 first_seen, last_seen, related_tags, suggested_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pattern_id, agent_id, pattern_type, description, frequency,
                 first_seen, last_seen, serialize_tags(related_tags), suggested_action)
            )
            await db.commit()
            return {"id": pattern_id, "updated": False}
    finally:
        await db.close()


async def analyze_reflections(agent_id: str, lookback_days: int = 7) -> Dict[str, Any]:
    """
    Analyze recent reflection logs to detect patterns.
    Returns list of detected patterns with suggested actions.
    Uses upsert logic — safe to call repeatedly without duplicating patterns.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM reflection_logs
            WHERE agent_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (agent_id, cutoff)
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    logs = []
    for row in rows:
        log = row_to_dict(row)
        log["tags"] = parse_tags(log.get("tags", "[]"))
        log["success"] = bool(log.get("success", 0))
        logs.append(log)

    if not logs:
        return {
            "patterns": [],
            "total_actions": 0,
            "success_rate": 0.0
        }

    patterns = []

    # 1. Repeated failures (same action fails N+ times)
    action_failures = defaultdict(list)
    for log in logs:
        if not log["success"]:
            action_failures[log["action"]].append(log)

    for action, failures in action_failures.items():
        if len(failures) >= settings.pattern_min_frequency:
            # Sort chronologically: oldest first
            failures_sorted = sorted(failures, key=lambda x: x["created_at"])
            description = f"Action '{action}' failed {len(failures)} times in the last {lookback_days} days"
            result = await _upsert_pattern(
                agent_id=agent_id,
                pattern_type="repeated_failure",
                description=description,
                frequency=len(failures),
                first_seen=failures_sorted[0]["created_at"],
                last_seen=failures_sorted[-1]["created_at"],
                related_tags=["failure", action],
                suggested_action=f"Consider reviewing approach for '{action}' or seeking alternative methods."
            )
            patterns.append({
                "id": result["id"],
                "pattern_type": "repeated_failure",
                "description": description,
                "frequency": len(failures),
                "suggested_action": f"Consider reviewing approach for '{action}'"
            })

    # 2. Success patterns (same action succeeds N+ times consistently)
    action_successes = defaultdict(list)
    for log in logs:
        if log["success"]:
            action_successes[log["action"]].append(log)

    for action, successes in action_successes.items():
        if len(successes) >= settings.pattern_min_frequency:
            successes_sorted = sorted(successes, key=lambda x: x["created_at"])
            description = f"Action '{action}' succeeded {len(successes)} times consistently"
            result = await _upsert_pattern(
                agent_id=agent_id,
                pattern_type="success_pattern",
                description=description,
                frequency=len(successes),
                first_seen=successes_sorted[0]["created_at"],
                last_seen=successes_sorted[-1]["created_at"],
                related_tags=["success", action],
                suggested_action=f"Continue using '{action}' approach — it has proven effective."
            )
            patterns.append({
                "id": result["id"],
                "pattern_type": "success_pattern",
                "description": description,
                "frequency": len(successes),
                "suggested_action": f"Continue using '{action}' approach"
            })

    # 3. Inefficiencies (low success rate with enough attempts)
    action_stats = defaultdict(lambda: {"total": 0, "success": 0,
                                        "timestamps": []})
    for log in logs:
        action_stats[log["action"]]["total"] += 1
        action_stats[log["action"]]["timestamps"].append(log["created_at"])
        if log["success"]:
            action_stats[log["action"]]["success"] += 1

    for action, stats in action_stats.items():
        if stats["total"] >= settings.pattern_min_frequency:
            success_rate = stats["success"] / stats["total"]
            if success_rate < 0.5:
                timestamps_sorted = sorted(stats["timestamps"])
                description = (
                    f"Action '{action}' has low success rate "
                    f"({success_rate:.0%}) over {stats['total']} attempts"
                )
                result = await _upsert_pattern(
                    agent_id=agent_id,
                    pattern_type="inefficiency",
                    description=description,
                    frequency=stats["total"],
                    first_seen=timestamps_sorted[0],
                    last_seen=timestamps_sorted[-1],
                    related_tags=["inefficiency", action],
                    suggested_action=(
                        f"Consider breaking down '{action}' into smaller steps "
                        "or getting more context first."
                    )
                )
                patterns.append({
                    "id": result["id"],
                    "pattern_type": "inefficiency",
                    "description": description,
                    "frequency": stats["total"],
                    "suggested_action": f"Consider breaking down '{action}' into smaller steps"
                })

    total_actions = len(logs)
    successful_actions = sum(1 for log in logs if log["success"])
    success_rate = successful_actions / total_actions if total_actions > 0 else 0.0

    return {
        "patterns": patterns,
        "total_actions": total_actions,
        "success_rate": round(success_rate, 2)
    }


async def get_patterns(agent_id: str, pattern_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return stored patterns detected from past reflection analysis."""
    db = await get_db()
    try:
        if pattern_type:
            cursor = await db.execute(
                """
                SELECT * FROM patterns
                WHERE agent_id = ? AND pattern_type = ?
                ORDER BY last_seen DESC
                """,
                (agent_id, pattern_type)
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM patterns
                WHERE agent_id = ?
                ORDER BY last_seen DESC
                """,
                (agent_id,)
            )

        rows = await cursor.fetchall()
        patterns = []
        for row in rows:
            pattern = row_to_dict(row)
            pattern["related_tags"] = parse_tags(pattern.get("related_tags", "[]"))
            patterns.append(pattern)

        return patterns
    finally:
        await db.close()


async def get_summary(agent_id: str, days: int = 7) -> Dict[str, Any]:
    """Return a summary of agent performance over N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT * FROM reflection_logs
            WHERE agent_id = ? AND created_at >= ?
            """,
            (agent_id, cutoff)
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    logs = []
    for row in rows:
        log = row_to_dict(row)
        log["success"] = bool(log.get("success", 0))
        logs.append(log)

    total_actions = len(logs)
    successful = sum(1 for log in logs if log["success"])
    success_rate = successful / total_actions if total_actions > 0 else 0.0

    # Most common failures
    failure_counts: Dict[str, int] = defaultdict(int)
    for log in logs:
        if not log["success"]:
            failure_counts[log["action"]] += 1
    most_common_failures = sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    # Most successful patterns
    success_counts: Dict[str, int] = defaultdict(int)
    for log in logs:
        if log["success"]:
            success_counts[log["action"]] += 1
    most_successful = sorted(success_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    # Top recommendations from stored patterns
    patterns = await get_patterns(agent_id)
    recommendations = [p["suggested_action"] for p in patterns[:3]]

    return {
        "total_actions": total_actions,
        "success_rate": round(success_rate, 2),
        "most_common_failures": most_common_failures,
        "most_successful_patterns": most_successful,
        "top_recommendations": recommendations
    }
