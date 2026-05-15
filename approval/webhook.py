"""
Webhook Notifier — sends HTTP POST to a configured URL
whenever a new approval is queued.

Configure via .env:
  WEBHOOK_URL=https://your-service.com/webhook
  WEBHOOK_SECRET=your-secret-token   (added as X-AgentOS-Secret header)
  WEBHOOK_ENABLED=true
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from loguru import logger

from config import settings


def notify(approval_item: dict):
    """
    Send a webhook notification for a new approval item.
    Fails silently — a webhook failure should never block the main flow.
    """
    if not getattr(settings, "webhook_enabled", False):
        return
    if not getattr(settings, "webhook_url", ""):
        return

    payload = {
        "event": "approval.pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "approval": {
            "id": approval_item.get("id"),
            "title": approval_item.get("title"),
            "description": approval_item.get("description", "")[:300],
            "action_type": approval_item.get("action_type"),
            "risk_score": approval_item.get("risk_score"),
            "risk_level": approval_item.get("risk_level"),
            "agent_id": approval_item.get("agent_id"),
            "created_at": approval_item.get("created_at"),
        }
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentOS/1.0",
        }
        if getattr(settings, "webhook_secret", ""):
            headers["X-AgentOS-Secret"] = settings.webhook_secret

        req = urllib.request.Request(
            url=settings.webhook_url,
            data=body,
            headers=headers,
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
            logger.info(
                f"[webhook] notified → {settings.webhook_url} "
                f"status={status} approval_id={approval_item.get('id')}"
            )

    except urllib.error.HTTPError as e:
        logger.warning(f"[webhook] HTTP {e.code} from {settings.webhook_url}")
    except urllib.error.URLError as e:
        logger.warning(f"[webhook] connection failed: {e.reason}")
    except Exception as e:
        logger.warning(f"[webhook] unexpected error: {e}")
