"""
MCP Tool Definitions for Context Module

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_context_tool(name, args): async dispatcher for call_tool()
"""

from modules.context.snapshot import build_snapshot
from approval.queue import get_pending_count


TOOL_SCHEMAS = [
    {
        "name": "context_get_snapshot",
        "description": (
            "Return a single unified snapshot of the agent's current cognitive state. "
            "Always call this at the start of a session. "
            "If pending_approvals > 0, call approval_list() to show the human "
            "what decisions are waiting before proceeding with other tasks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "include_memories": {"type": "integer", "description": "Number of memories to include", "default": 5},
                "include_goals": {"type": "integer", "description": "Number of goals to include", "default": 5},
                "include_patterns": {"type": "integer", "description": "Number of patterns to include", "default": 3},
            },
            "required": ["agent_id"],
        },
    },
]


async def handle_context_tool(name: str, args: dict) -> dict:
    """Dispatch context tool call to the appropriate handler."""
    if name == "context_get_snapshot":
        return await _context_get_snapshot(args)
    return {"success": False, "data": None, "error": f"Unknown context tool: {name}"}


async def _context_get_snapshot(args: dict) -> dict:
    try:
        result = await build_snapshot(
            agent_id=args["agent_id"],
            include_memories=args.get("include_memories", 5),
            include_goals=args.get("include_goals", 5),
            include_patterns=args.get("include_patterns", 3),
        )
        pending = get_pending_count(args["agent_id"])
        result["pending_approvals"] = pending
        if pending > 0:
            result["approval_alert"] = (
                f"⚠️ يوجد {pending} قرار ينتظر موافقتك — "
                "استخدم approval_list() للاطلاع عليها."
            )
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
