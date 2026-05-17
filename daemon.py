"""
AgentOS Daemon — Background Process

Runs independently from the MCP server.
Continuously monitors agents, generates insights,
applies memory decay, and creates autonomous tasks.

Usage:
    python daemon.py

The daemon writes to the same SQLite database as the MCP server.
When an agent calls context_get_snapshot, it will find the insights
and autonomous tasks generated here.
"""

import sys
import signal
import time
import sqlite3
import threading
from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

import sys
import os

# Resolve the project root: when running from source, use the source directory;
# when installed via pip, database.py already computes the correct DB_PATH.
# We just need to ensure the project root is on sys.path for imports.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import settings
from database import init_db, DB_PATH
from events.store import init_event_store, purge_old_events
from events.dispatcher import run_dispatch_loop
from approval.executor import run as run_executor
from daemon_pkg.jobs import (
    memory_decay_job,
    goal_monitor_job,
    reflection_analyzer_job,
    self_maintenance_job,
)

# ── Logging ──────────────────────────────────────────────────────────────────
logger.remove()
logger.add(sys.stdout, level=settings.log_level, colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add(settings.log_file.replace(".log", "_daemon.log"),
           level="DEBUG", rotation="10 MB", retention="7 days")


# ── Scheduler callbacks ───────────────────────────────────────────────────────
def _on_job_error(event):
    logger.error(f"Job {event.job_id} raised an exception: {event.exception}")


def _on_job_executed(event):
    logger.debug(f"Job {event.job_id} executed successfully")


# ── Job wrappers (sync, APScheduler needs sync functions) ────────────────────
def run_memory_decay():
    try:
        memory_decay_job.run(DB_PATH)
    except Exception as e:
        logger.error(f"[memory_decay] Unhandled error: {e}")


def run_goal_monitor():
    try:
        goal_monitor_job.run(DB_PATH)
    except Exception as e:
        logger.error(f"[goal_monitor] Unhandled error: {e}")


def run_reflection_analyzer():
    try:
        reflection_analyzer_job.run(DB_PATH)
    except Exception as e:
        logger.error(f"[reflection_analyzer] Unhandled error: {e}")


def run_self_maintenance():
    try:
        self_maintenance_job.run(DB_PATH)
    except Exception as e:
        logger.error(f"[self_maintenance] Unhandled error: {e}")


def run_heartbeat():
    """Write daemon status to DB so agents can verify daemon is alive."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO daemon_heartbeat (agent_id, last_seen, jobs_run, status)
            VALUES ('__daemon__', ?, 0, 'running')
            ON CONFLICT(agent_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                status = 'running'
            """,
            (datetime.now(timezone.utc).isoformat(),)
        )
        conn.commit()
    finally:
        conn.close()


def run_executor_job():
    try:
        run_executor(DB_PATH)
    except Exception as e:
        logger.error(f"[executor_job] Unhandled error: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("  AgentOS Daemon starting")
    logger.info(f"  DB: {DB_PATH}")
    logger.info("=" * 60)

    # Ensure DB and tables exist
    init_db()
    init_event_store()

    # ── Start event dispatcher thread ─────────────────────────────────────────
    dispatcher_thread = threading.Thread(
        target=run_dispatch_loop,
        kwargs={"poll_interval_seconds": 5},
        name="EventDispatcher",
        daemon=True   # dies automatically when main process exits
    )
    dispatcher_thread.start()
    logger.info("Event dispatcher started (polling every 5s)")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)

    # ── Schedule jobs ─────────────────────────────────────────────────────────
    # Action Executor — every 2 minutes
    scheduler.add_job(
        run_executor_job,
        trigger="interval", minutes=2,
        id="action_executor", name="Action Executor"
    )

    # Heartbeat — every 1 minute
    scheduler.add_job(
        run_heartbeat,
        trigger="interval", minutes=1,
        id="heartbeat", name="Daemon Heartbeat"
    )

    # Reflection analyzer — every 30 minutes
    scheduler.add_job(
        run_reflection_analyzer,
        trigger="interval", minutes=30,
        id="reflection_analyzer", name="Reflection Analyzer"
    )

    # Goal monitor — every 60 minutes
    scheduler.add_job(
        run_goal_monitor,
        trigger="interval", minutes=60,
        id="goal_monitor", name="Goal Monitor"
    )

    # Self maintenance — every 6 hours
    scheduler.add_job(
        run_self_maintenance,
        trigger="interval", hours=6,
        id="self_maintenance", name="Self Maintenance"
    )

    # Memory decay — every 24 hours
    scheduler.add_job(
        run_memory_decay,
        trigger="interval", hours=24,
        id="memory_decay", name="Memory Decay"
    )

    # Event store purge — every 24 hours
    scheduler.add_job(
        purge_old_events,
        trigger="interval", hours=24,
        id="event_purge", name="Event Store Purge"
    )

    # ── Run all jobs immediately on startup ───────────────────────────────────
    logger.info("Running all jobs immediately on startup...")
    run_heartbeat()
    run_executor_job()
    run_reflection_analyzer()
    run_goal_monitor()
    run_self_maintenance()
    # Note: memory decay is skipped on startup to avoid immediate score changes

    scheduler.start()

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def _shutdown(signum, frame):
        logger.info("Shutdown signal received — stopping daemon...")
        scheduler.shutdown(wait=False)

        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "UPDATE daemon_heartbeat SET status = 'stopped' WHERE agent_id = '__daemon__'"
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Daemon stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Daemon running. Press Ctrl+C to stop.")
    logger.info("Scheduled jobs:")
    logger.info("  • Action Executor     → every 2 min")
    logger.info("  • Heartbeat           → every 1 min")
    logger.info("  • Reflection Analyzer → every 30 min")
    logger.info("  • Goal Monitor        → every 60 min")
    logger.info("  • Self Maintenance    → every 6 hours")
    logger.info("  • Memory Decay        → every 24 hours")
    logger.info("  • Event Store Purge   → every 24 hours")
    logger.info("Reactive jobs:")
    logger.info("  • Event Dispatcher    → polling every 5s")

    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
