"""
Async In-Process Event Bus — MCP Server side.

Publishes events both:
1. To the SQLite store (for the daemon to pick up)
2. To any in-process async subscribers (for future extensions)

Usage:
    from events.bus import get_bus

    bus = get_bus()
    await bus.emit(memory_stored(agent_id, memory_id, ...))
"""

import asyncio
from collections import defaultdict
from typing import Callable, Awaitable
from loguru import logger

from events.schema import Event
from events import store as event_store


# Handler type: async function that receives an Event
Handler = Callable[[Event], Awaitable[None]]


class AsyncEventBus:
    """
    Lightweight async event bus for intra-process communication.
    Persists every event to SQLite for the daemon automatically.
    """

    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._wildcard_handlers: list[Handler] = []

    def subscribe(self, event_type: str, handler: Handler):
        """Subscribe a handler to a specific event type."""
        self._handlers[event_type].append(handler)
        logger.debug(f"[bus] subscribed {handler.__name__} to {event_type}")

    def subscribe_all(self, handler: Handler):
        """Subscribe a handler to ALL event types."""
        self._wildcard_handlers.append(handler)

    async def emit(self, event: Event):
        """
        Emit an event:
        1. Persist to SQLite event store (for daemon)
        2. Notify in-process subscribers (for extensions)
        """
        # Always persist to SQLite
        try:
            event_store.publish(event)
        except Exception as e:
            logger.error(f"[bus] failed to persist event {event.event_type}: {e}")

        # Notify in-process handlers (fire and forget — don't block MCP tools)
        handlers = self._handlers.get(event.event_type, []) + self._wildcard_handlers
        if handlers:
            tasks = [asyncio.create_task(_safe_call(h, event)) for h in handlers]
            # Don't await — background tasks
            _ = tasks

    def clear(self):
        """Remove all subscriptions. Useful for testing."""
        self._handlers.clear()
        self._wildcard_handlers.clear()


async def _safe_call(handler: Handler, event: Event):
    """Call a handler and swallow exceptions so one bad handler can't crash the bus."""
    try:
        await handler(event)
    except Exception as e:
        logger.error(f"[bus] handler {handler.__name__} raised: {e}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_bus: AsyncEventBus | None = None


def get_bus() -> AsyncEventBus:
    """Return the global event bus singleton."""
    global _bus
    if _bus is None:
        _bus = AsyncEventBus()
    return _bus
