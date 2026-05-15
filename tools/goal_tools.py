"""
MCP Tool Definitions for Goals Module

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_goal_tool(name, args): async dispatcher for call_tool()
"""

from typing import List

from modules.goals.manager import (
    add_goal, get_active_goals, update_goal_progress,
    update_goal_status, list_goals,
)
from events.bus import get_bus
from events.schema import goal_added, goal_updated, goal_completed


TOOL_SCHEMAS = [
    {
        "name": "goal_add",
        "description": (
            "Add a new goal for the agent. "
            "Returns the created goal with computed composite_score."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "title": {"type": "string", "description": "Goal title"},
                "description": {"type": "string", "description": "Goal description"},
                "priority": {"type": "number", "description": "Priority 0-1", "default": 0.5},
                "urgency": {"type": "number", "description": "Urgency 0-1", "default": 0.5},
                "deadline": {"type": "string", "description": "Deadline (ISO format)", "default": None},
                "parent_goal_id": {"type": "string", "description": "Parent goal ID for sub-goals", "default": None},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags", "default": []},
            },
            "required": ["agent_id", "title", "description"],
        },
    },
    {
        "name": "goal_get_active",
        "description": (
            "Return active goals sorted by composite priority score. "
            "Composite = priority*0.5 + urgency*0.3 + deadline_pressure*0.2"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "goal_update_progress",
        "description": (
            "Update progress on a goal. "
            "Automatically marks as completed if progress >= 1.0"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "goal_id": {"type": "string", "description": "The goal ID"},
                "progress": {"type": "number", "description": "Progress 0-1"},
                "notes": {"type": "string", "description": "Optional notes", "default": None},
            },
            "required": ["agent_id", "goal_id", "progress"],
        },
    },
    {
        "name": "goal_update_status",
        "description": "Change the status of a goal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "goal_id": {"type": "string", "description": "The goal ID"},
                "status": {"type": "string", "description": "New status (active, completed, paused, cancelled)"},
                "notes": {"type": "string", "description": "Optional notes", "default": None},
            },
            "required": ["agent_id", "goal_id", "status"],
        },
    },
    {
        "name": "goal_list",
        "description": "List goals filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "status": {"type": "string", "description": "Filter by status", "default": "active"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
            "required": ["agent_id"],
        },
    },
]


async def handle_goal_tool(name: str, args: dict) -> dict:
    """Dispatch goal tool call to the appropriate handler."""
    if name == "goal_add":
        return await _goal_add(args)
    elif name == "goal_get_active":
        return await _goal_get_active(args)
    elif name == "goal_update_progress":
        return await _goal_update_progress(args)
    elif name == "goal_update_status":
        return await _goal_update_status(args)
    elif name == "goal_list":
        return await _goal_list(args)
    return {"success": False, "data": None, "error": f"Unknown goal tool: {name}"}


async def _goal_add(args: dict) -> dict:
    tags = args.get("tags", [])
    if tags is None:
        tags = []
    try:
        result = await add_goal(
            agent_id=args["agent_id"],
            title=args["title"],
            description=args["description"],
            priority=args.get("priority", 0.5),
            urgency=args.get("urgency", 0.5),
            deadline=args.get("deadline"),
            parent_goal_id=args.get("parent_goal_id"),
            tags=tags,
        )
        await get_bus().emit(goal_added(
            agent_id=args["agent_id"],
            goal_id=result["id"],
            title=args["title"],
            priority=args.get("priority", 0.5),
            deadline=args.get("deadline"),
        ))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _goal_get_active(args: dict) -> dict:
    try:
        results = await get_active_goals(args["agent_id"], args.get("limit", 10))
        return {"success": True, "data": results, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


async def _goal_update_progress(args: dict) -> dict:
    try:
        result = await update_goal_progress(
            args["agent_id"], args["goal_id"],
            args["progress"], args.get("notes"),
        )
        if result is None:
            return {"success": False, "data": None, "error": "Goal not found or access denied"}
        if result.get("status") == "completed":
            await get_bus().emit(goal_completed(
                args["agent_id"], args["goal_id"], result.get("title", "")
            ))
        else:
            await get_bus().emit(goal_updated(
                args["agent_id"], args["goal_id"],
                args["progress"], result.get("status", ""),
            ))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _goal_update_status(args: dict) -> dict:
    try:
        result = await update_goal_status(
            args["agent_id"], args["goal_id"],
            args["status"], args.get("notes"),
        )
        if result is None:
            return {"success": False, "data": None, "error": "Goal not found or access denied"}
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _goal_list(args: dict) -> dict:
    try:
        results = await list_goals(
            args["agent_id"], args.get("status", "active"), args.get("limit", 20)
        )
        return {"success": True, "data": results, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}
