"""
MCP Tool Definitions — Approval Queue

These tools allow the agent to surface pending decisions
to the human and relay their response back to the system.

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_approval_tool(name, args): async dispatcher for call_tool()
"""

from approval.queue import (
    list_pending,
    list_history,
    get_item,
    submit_decision,
    get_pending_count,
)


TOOL_SCHEMAS = [
    {
        "name": "approval_list",
        "description": (
            "Return all pending decisions waiting for human approval. "
            "Call this at the start of a session or when notified of pending items. "
            "Items are sorted by risk score — highest risk first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "approval_get_details",
        "description": (
            "Get full details of a specific approval item including "
            "the complete action payload and risk breakdown. "
            "Use this before making a decision on an important item."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "approval_id": {"type": "string", "description": "Approval item ID"},
            },
            "required": ["agent_id", "approval_id"],
        },
    },
    {
        "name": "approval_decide",
        "description": (
            "Submit a human decision on a pending approval. "
            "decision: 'approved' to allow the action, 'rejected' to cancel it. "
            "notes: optional reason for the decision (recommended for rejections). "
            "The system will execute approved actions on the next daemon cycle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "approval_id": {"type": "string", "description": "Approval item ID"},
                "decision": {"type": "string", "description": "'approved' | 'rejected'"},
                "notes": {"type": "string", "description": "Optional reason", "default": ""},
            },
            "required": ["agent_id", "approval_id", "decision"],
        },
    },
    {
        "name": "approval_history",
        "description": (
            "View past decisions — approved and rejected actions. "
            "Useful for auditing what the system has done."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "status": {"type": "string", "description": "'approved' | 'rejected' | None for all", "default": None},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
            "required": ["agent_id"],
        },
    },
]


async def handle_approval_tool(name: str, args: dict) -> dict:
    """Dispatch approval tool call to the appropriate handler."""
    if name == "approval_list":
        return await _approval_list(args)
    elif name == "approval_get_details":
        return await _approval_get_details(args)
    elif name == "approval_decide":
        return await _approval_decide(args)
    elif name == "approval_history":
        return await _approval_history(args)
    return {"success": False, "data": None, "error": f"Unknown approval tool: {name}"}


async def _approval_list(args: dict) -> dict:
    try:
        items = list_pending(agent_id=args["agent_id"], limit=args.get("limit", 20))
        return {
            "success": True,
            "data": {"pending_count": len(items), "items": items},
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _approval_get_details(args: dict) -> dict:
    try:
        item = get_item(item_id=args["approval_id"], agent_id=args["agent_id"])
        if not item:
            return {"success": False, "data": None, "error": "Approval item not found"}
        return {"success": True, "data": item, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _approval_decide(args: dict) -> dict:
    decision = args["decision"]
    if decision not in ("approved", "rejected"):
        return {"success": False, "data": None, "error": "decision must be 'approved' or 'rejected'"}
    try:
        result = submit_decision(
            item_id=args["approval_id"],
            agent_id=args["agent_id"],
            decision=decision,
            notes=args.get("notes", ""),
            decided_by="human_via_agent",
        )
        if not result:
            return {"success": False, "data": None, "error": "Item not found or already decided"}
        return {
            "success": True,
            "data": {
                "id": args["approval_id"],
                "decision": decision,
                "message": (
                    "✅ تم الموافقة — سيُنفذ في الدورة القادمة."
                    if decision == "approved"
                    else "❌ تم الرفض — لن يُنفذ هذا الإجراء."
                ),
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _approval_history(args: dict) -> dict:
    try:
        items = list_history(
            agent_id=args["agent_id"],
            status=args.get("status"),
            limit=args.get("limit", 20),
        )
        return {"success": True, "data": items, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}
