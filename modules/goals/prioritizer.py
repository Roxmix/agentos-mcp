"""
Goals Module - Priority Scoring Algorithm
"""

from datetime import datetime, timezone
from typing import Dict, Any


def calculate_deadline_pressure(deadline_str: str) -> float:
    """
    Calculate deadline pressure based on how close the deadline is.
    Returns 0.0 to 1.0 where 1.0 means deadline is now or passed.
    """
    if not deadline_str:
        return 0.0

    try:
        deadline = datetime.fromisoformat(deadline_str)
        now = datetime.now(timezone.utc)

        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        if deadline <= now:
            return 1.0

        # Calculate time until deadline
        time_until = (deadline - now).total_seconds()

        # Pressure increases as deadline approaches
        # Full pressure at 24 hours or less
        seconds_in_day = 86400
        pressure = max(0.0, 1.0 - (time_until / (seconds_in_day * 7)))

        return min(1.0, pressure)
    except:
        return 0.0


def calculate_composite_score(goal: Dict[str, Any]) -> float:
    """
    Composite score = (priority * 0.5) + (urgency * 0.3) + (deadline_pressure * 0.2)
    """
    priority = goal.get("priority", 0.5)
    urgency = goal.get("urgency", 0.5)
    deadline = goal.get("deadline")

    deadline_pressure = calculate_deadline_pressure(deadline)

    composite = (priority * 0.5) + (urgency * 0.3) + (deadline_pressure * 0.2)
    return round(composite, 4)
