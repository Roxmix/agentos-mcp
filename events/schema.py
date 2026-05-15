"""
Event Schema — All event types in AgentOS.

Every action in the system emits a typed event.
Events flow from MCP Server → SQLite → Daemon.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


# ── Event Type Constants ──────────────────────────────────────────────────────

class EventType:
    # Memory events
    MEMORY_STORED  = "memory.stored"
    MEMORY_DELETED = "memory.deleted"
    MEMORY_DECAYED = "memory.decayed"

    # Goal events
    GOAL_ADDED     = "goal.added"
    GOAL_UPDATED   = "goal.updated"
    GOAL_COMPLETED = "goal.completed"
    GOAL_OVERDUE   = "goal.overdue"
    GOAL_STALLED   = "goal.stalled"

    # Reflection events
    REFLECTION_LOGGED  = "reflection.logged"
    REFLECTION_FAILED  = "reflection.failed"   # shortcut: success=False
    PATTERN_DETECTED   = "pattern.detected"

    # Insight events
    INSIGHT_GENERATED  = "insight.generated"
    TASK_GENERATED     = "task.generated"

    # System events
    DAEMON_STARTED     = "daemon.started"
    DAEMON_CYCLE       = "daemon.cycle"


# ── Event Model ───────────────────────────────────────────────────────────────

@dataclass
class Event:
    event_type: str
    agent_id: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "mcp_server"   # "mcp_server" | "daemon"
    processed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "created_at": self.created_at,
            "source": self.source,
            "processed": self.processed,
        }


# ── Event Factories ───────────────────────────────────────────────────────────

def memory_stored(agent_id: str, memory_id: str, memory_type: str,
                  importance: float, tags: list) -> Event:
    return Event(
        event_type=EventType.MEMORY_STORED,
        agent_id=agent_id,
        payload={
            "memory_id": memory_id,
            "memory_type": memory_type,
            "importance": importance,
            "tags": tags,
        }
    )


def memory_deleted(agent_id: str, memory_id: str) -> Event:
    return Event(
        event_type=EventType.MEMORY_DELETED,
        agent_id=agent_id,
        payload={"memory_id": memory_id}
    )


def goal_added(agent_id: str, goal_id: str, title: str,
               priority: float, deadline: str | None) -> Event:
    return Event(
        event_type=EventType.GOAL_ADDED,
        agent_id=agent_id,
        payload={
            "goal_id": goal_id,
            "title": title,
            "priority": priority,
            "deadline": deadline,
        }
    )


def goal_completed(agent_id: str, goal_id: str, title: str) -> Event:
    return Event(
        event_type=EventType.GOAL_COMPLETED,
        agent_id=agent_id,
        payload={"goal_id": goal_id, "title": title}
    )


def goal_updated(agent_id: str, goal_id: str, progress: float,
                 status: str) -> Event:
    return Event(
        event_type=EventType.GOAL_UPDATED,
        agent_id=agent_id,
        payload={"goal_id": goal_id, "progress": progress, "status": status}
    )


def reflection_logged(agent_id: str, log_id: str, action: str,
                      success: bool, tags: list) -> Event:
    etype = EventType.REFLECTION_FAILED if not success else EventType.REFLECTION_LOGGED
    return Event(
        event_type=etype,
        agent_id=agent_id,
        payload={
            "log_id": log_id,
            "action": action,
            "success": success,
            "tags": tags,
        }
    )


def pattern_detected(agent_id: str, pattern_id: str, pattern_type: str,
                     description: str, frequency: int) -> Event:
    return Event(
        event_type=EventType.PATTERN_DETECTED,
        agent_id=agent_id,
        payload={
            "pattern_id": pattern_id,
            "pattern_type": pattern_type,
            "description": description,
            "frequency": frequency,
        }
    )
