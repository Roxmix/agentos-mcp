"""
Job: Memory Decay
Runs: every 24 hours

Reduces decay_score of memories that haven't been accessed recently.
High-importance memories decay slower.
Generates an insight if critical memories are near-forgotten.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from loguru import logger

from daemon.writer import write_insight, get_all_agent_ids


JOB_NAME = "memory_decay"


def run(db_path: str):
    logger.info(f"[{JOB_NAME}] Starting memory decay job")
    agent_ids = get_all_agent_ids(db_path)

    for agent_id in agent_ids:
        _decay_for_agent(db_path, agent_id)

    logger.info(f"[{JOB_NAME}] Done — processed {len(agent_ids)} agents")


def _decay_for_agent(db_path: str, agent_id: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)

    try:
        rows = conn.execute(
            "SELECT * FROM memories WHERE agent_id = ?",
            (agent_id,)
        ).fetchall()

        decayed_count = 0
        near_forgotten = []

        for row in rows:
            memory = dict(row)

            # Calculate days since last access
            last_accessed_str = memory.get("last_accessed") or memory["created_at"]
            try:
                last_accessed = datetime.fromisoformat(last_accessed_str)
                if last_accessed.tzinfo is None:
                    last_accessed = last_accessed.replace(tzinfo=timezone.utc)
            except Exception:
                last_accessed = now

            days_since_access = (now - last_accessed).days

            # High importance = slower decay
            importance = memory.get("importance", 0.5)
            # decay_rate slows proportionally to importance
            # importance=1.0 → no decay, importance=0.0 → full decay rate
            effective_rate = 0.02 * (1.0 - importance)
            decay_amount = effective_rate * days_since_access

            current_decay = memory.get("decay_score", 1.0)
            new_decay = max(0.0, current_decay - decay_amount)

            if new_decay != current_decay:
                conn.execute(
                    "UPDATE memories SET decay_score = ? WHERE id = ?",
                    (round(new_decay, 4), memory["id"])
                )
                decayed_count += 1

            # Flag important memories that are near forgotten
            if importance >= 0.7 and new_decay < 0.2:
                near_forgotten.append(memory["summary"] or memory["content"][:80])

        conn.commit()
        logger.info(
            f"[{JOB_NAME}] agent={agent_id}: "
            f"decayed={decayed_count}, near_forgotten={len(near_forgotten)}"
        )

        # Write insights for near-forgotten important memories
        for summary in near_forgotten[:3]:  # cap at 3 insights per run
            write_insight(
                db_path=db_path,
                agent_id=agent_id,
                insight=(
                    f"ذاكرة مهمة على وشك الاندثار: \"{summary[:100]}\" — "
                    "يُنصح بمراجعتها أو رفع أهميتها."
                ),
                insight_type="memory_conflict",
                severity="warning",
                source_job=JOB_NAME
            )

    finally:
        conn.close()
