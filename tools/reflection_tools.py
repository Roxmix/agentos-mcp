"""
MCP Tool Definitions for Reflection Module

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_reflection_tool(name, args): async dispatcher for call_tool()
"""

from typing import List

from modules.reflection.logger import log_reflection
from modules.reflection.analyzer import analyze_reflections, get_patterns, get_summary
from events.bus import get_bus
from events.schema import reflection_logged


TOOL_SCHEMAS = [
    {
        "name": "reflection_log",
        "description": "Log an action and its outcome for later reflection analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "action": {"type": "string", "description": "Action that was taken"},
                "outcome": {"type": "string", "description": "Outcome of the action"},
                "success": {"type": "boolean", "description": "Whether the action was successful"},
                "context": {"type": "string", "description": "Additional context", "default": ""},
                "goal_id": {"type": "string", "description": "Associated goal ID", "default": None},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags", "default": []},
            },
            "required": ["agent_id", "action", "outcome", "success"],
        },
    },
    {
        "name": "reflection_analyze",
        "description": (
            "Analyze recent reflection logs to detect repeated failures, "
            "success patterns, and inefficiencies. "
            "Returns list of detected patterns with suggested actions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "lookback_days": {"type": "integer", "description": "Days to look back", "default": 7},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "reflection_get_patterns",
        "description": "Return stored patterns detected from past reflection analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "pattern_type": {"type": "string", "description": "Filter by pattern type", "default": None},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "reflection_get_summary",
        "description": (
            "Return a summary of agent performance over N days: "
            "total_actions, success_rate, most_common_failures, "
            "most_successful_patterns, top_recommendations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "days": {"type": "integer", "description": "Number of days", "default": 7},
            },
            "required": ["agent_id"],
        },
    },
]


async def handle_reflection_tool(name: str, args: dict) -> dict:
    """Dispatch reflection tool call to the appropriate handler."""
    if name == "reflection_log":
        return await _reflection_log(args)
    elif name == "reflection_analyze":
        return await _reflection_analyze(args)
    elif name == "reflection_get_patterns":
        return await _reflection_get_patterns(args)
    elif name == "reflection_get_summary":
        return await _reflection_get_summary(args)
    return {"success": False, "data": None, "error": f"Unknown reflection tool: {name}"}


async def _reflection_log(args: dict) -> dict:
    tags = args.get("tags", [])
    if tags is None:
        tags = []
    try:
        result = await log_reflection(
            agent_id=args["agent_id"],
            action=args["action"],
            outcome=args["outcome"],
            success=args["success"],
            context=args.get("context", ""),
            goal_id=args.get("goal_id"),
            tags=tags,
        )
        await get_bus().emit(reflection_logged(
            agent_id=args["agent_id"],
            log_id=result["id"],
            action=args["action"],
            success=args["success"],
            tags=tags,
        ))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _reflection_analyze(args: dict) -> dict:
    try:
        result = await analyze_reflections(args["agent_id"], args.get("lookback_days", 7))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _reflection_get_patterns(args: dict) -> dict:
    try:
        results = await get_patterns(args["agent_id"], args.get("pattern_type"))
        return {"success": True, "data": results, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


async def _reflection_get_summary(args: dict) -> dict:
    try:
        result = await get_summary(args["agent_id"], args.get("days", 7))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
