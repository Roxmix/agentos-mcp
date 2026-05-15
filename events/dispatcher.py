"""
Event Dispatcher — Daemon side.

Polls the SQLite event store for new events,
routes each event to the correct handler,
and marks it as processed.

This makes the daemon REACTIVE (responds to events immediately)
instead of only SCHEDULED (runs every N minutes).
"""

import time
from loguru import logger

from events import store as event_store
from events.schema import EventType
from events.handlers import (
    memory_handlers,
    goal_handlers,
    reflection_handlers,
)
from database import DB_PATH


# Map event types → handler functions
# Each handler receives (event_dict, db_path) and returns None
HANDLER_MAP = {
    EventType.MEMORY_STORED:    memory_handlers.on_memory_stored,
    EventType.MEMORY_DELETED:   memory_handlers.on_memory_deleted,

    EventType.GOAL_ADDED:       goal_handlers.on_goal_added,
    EventType.GOAL_UPDATED:     goal_handlers.on_goal_updated,
    EventType.GOAL_COMPLETED:   goal_handlers.on_goal_completed,

    EventType.REFLECTION_LOGGED: reflection_handlers.on_reflection_logged,
    EventType.REFLECTION_FAILED: reflection_handlers.on_reflection_failed,
    EventType.PATTERN_DETECTED:  reflection_handlers.on_pattern_detected,
}


def dispatch_pending(batch_size: int = 50) -> int:
    """
    Claim and dispatch all pending events.
    Returns the number of events processed.
    Called by the daemon on each polling cycle.
    """
    events = event_store.claim_pending(batch_size=batch_size)

    if not events:
        return 0

    processed_ids = []
    failed_ids = []

    for event in events:
        event_type = event["event_type"]
        handler = HANDLER_MAP.get(event_type)

        if handler is None:
            # Unknown event type — mark as processed to avoid blocking
            logger.debug(f"[dispatcher] no handler for {event_type} — skipping")
            processed_ids.append(event["id"])
            continue

        try:
            handler(event, DB_PATH)
            processed_ids.append(event["id"])
            logger.debug(
                f"[dispatcher] processed {event_type} "
                f"agent={event['agent_id']}"
            )
        except Exception as e:
            logger.error(
                f"[dispatcher] handler for {event_type} failed: {e} "
                f"— event will be retried"
            )
            failed_ids.append(event["id"])

    if processed_ids:
        event_store.mark_processed(processed_ids)

    if failed_ids:
        for eid in failed_ids:
            event_store.mark_failed(eid)

    return len(processed_ids)


def run_dispatch_loop(poll_interval_seconds: int = 5):
    """
    Continuous polling loop. Runs in the daemon as a background thread.
    Polls every N seconds for new events.
    """
    logger.info(f"[dispatcher] Starting — polling every {poll_interval_seconds}s")

    while True:
        try:
            count = dispatch_pending()
            if count > 0:
                logger.info(f"[dispatcher] Dispatched {count} events")
        except Exception as e:
            logger.error(f"[dispatcher] Poll cycle failed: {e}")

        time.sleep(poll_interval_seconds)
