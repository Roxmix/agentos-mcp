"""
Goal Event Handlers — Daemon side.
Reacts to goal events in real-time.
"""

from loguru import logger
from daemon.writer import write_insight, write_autonomous_task


def on_goal_added(event: dict, db_path: str):
    """
    Triggered when a new goal is added.
    Immediately flags high-priority goals with no deadline.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    title = payload.get("title", "")
    priority = payload.get("priority", 0.5)
    deadline = payload.get("deadline")

    logger.debug(f"[goal_handler] goal.added agent={agent_id} title='{title}'")

    if priority >= 0.8 and not deadline:
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=(
                f"⚠️ الهدف \"{title}\" أولويته عالية ({priority}) "
                "لكن لا يوجد له موعد نهائي — فكر في تحديد deadline."
            ),
            insight_type="goal_alert",
            severity="info",
            source_job="event:goal.added"
        )


def on_goal_updated(event: dict, db_path: str):
    """
    Triggered when goal progress is updated.
    Celebrates milestones.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    goal_id = payload.get("goal_id")
    progress = payload.get("progress", 0.0)

    logger.debug(
        f"[goal_handler] goal.updated agent={agent_id} "
        f"id={goal_id} progress={progress:.0%}"
    )

    # Milestone insight at 50%
    if 0.48 <= progress <= 0.52:
        write_insight(
            db_path=db_path,
            agent_id=agent_id,
            insight=f"🎯 وصلت إلى منتصف الطريق في أحد أهدافك ({progress:.0%}).",
            insight_type="goal_alert",
            severity="info",
            source_job="event:goal.updated"
        )


def on_goal_completed(event: dict, db_path: str):
    """
    Triggered when a goal is completed.
    Creates a completion insight and suggests creating the next goal.
    """
    payload = event["payload"]
    agent_id = event["agent_id"]
    title = payload.get("title", "")

    logger.info(f"[goal_handler] goal.completed agent={agent_id} title='{title}'")

    write_insight(
        db_path=db_path,
        agent_id=agent_id,
        insight=f"✅ تم إنجاز الهدف: \"{title}\" — أحسنت!",
        insight_type="goal_alert",
        severity="info",
        source_job="event:goal.completed"
    )

    write_autonomous_task(
        db_path=db_path,
        agent_id=agent_id,
        title=f"مراجعة الدروس المستفادة من: {title}",
        reason="الهدف اكتمل — وقت مناسب للتأمل واستخلاص الدروس.",
        priority=0.4,
        source_job="event:goal.completed"
    )
