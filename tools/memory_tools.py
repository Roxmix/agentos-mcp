"""
MCP Tool Definitions for Memory Module

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_memory_tool(name, args): async dispatcher for call_tool()
"""

from typing import List

from modules.memory.store import store_memory, delete_memory, update_memory_importance
from modules.memory.retriever import search_memories, list_memories
from events.bus import get_bus
from events.schema import memory_stored, memory_deleted


TOOL_SCHEMAS = [
    {
        "name": "memory_store",
        "description": (
            "Store a new memory for the agent. "
            "Automatically generates embedding and summary. "
            "Returns the created memory ID."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "content": {"type": "string", "description": "Memory content to store"},
                "memory_type": {"type": "string", "description": "Type of memory (episodic, semantic, procedural)", "default": "episodic"},
                "importance": {"type": "number", "description": "Importance score 0-1", "default": 0.5},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for the memory", "default": []},
            },
            "required": ["agent_id", "content"],
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Semantically search memories relevant to a query. "
            "Returns top-k memories ranked by relevance + recency + importance. "
            "Also updates last_accessed and access_count for returned memories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
                "memory_type": {"type": "string", "description": "Filter by memory type", "default": None},
                "min_importance": {"type": "number", "description": "Minimum importance threshold", "default": 0.0},
            },
            "required": ["agent_id", "query"],
        },
    },
    {
        "name": "memory_list",
        "description": "List recent memories with optional type filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "memory_type": {"type": "string", "description": "Filter by memory type", "default": None},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
                "offset": {"type": "integer", "description": "Offset for pagination", "default": 0},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "memory_update_importance",
        "description": "Update the importance score of a specific memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "memory_id": {"type": "string", "description": "The memory ID to update"},
                "importance": {"type": "number", "description": "New importance score 0-1"},
            },
            "required": ["agent_id", "memory_id", "importance"],
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a specific memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "memory_id": {"type": "string", "description": "The memory ID to delete"},
            },
            "required": ["agent_id", "memory_id"],
        },
    },
]


async def handle_memory_tool(name: str, args: dict) -> dict:
    """Dispatch memory tool call to the appropriate handler."""
    if name == "memory_store":
        return await _memory_store(args)
    elif name == "memory_search":
        return await _memory_search(args)
    elif name == "memory_list":
        return await _memory_list(args)
    elif name == "memory_update_importance":
        return await _memory_update_importance(args)
    elif name == "memory_delete":
        return await _memory_delete(args)
    return {"success": False, "data": None, "error": f"Unknown memory tool: {name}"}


async def _memory_store(args: dict) -> dict:
    tags = args.get("tags", [])
    if tags is None:
        tags = []
    try:
        result = await store_memory(
            agent_id=args["agent_id"],
            content=args["content"],
            memory_type=args.get("memory_type", "episodic"),
            importance=args.get("importance", 0.5),
            tags=tags,
        )
        await get_bus().emit(memory_stored(
            agent_id=args["agent_id"],
            memory_id=result["id"],
            memory_type=args.get("memory_type", "episodic"),
            importance=args.get("importance", 0.5),
            tags=tags,
        ))
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _memory_search(args: dict) -> dict:
    try:
        results = await search_memories(
            agent_id=args["agent_id"],
            query=args["query"],
            limit=args.get("limit", 5),
            memory_type=args.get("memory_type"),
            min_importance=args.get("min_importance", 0.0),
        )
        return {"success": True, "data": results, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


async def _memory_list(args: dict) -> dict:
    try:
        results = await list_memories(
            agent_id=args["agent_id"],
            memory_type=args.get("memory_type"),
            limit=args.get("limit", 20),
            offset=args.get("offset", 0),
        )
        return {"success": True, "data": results, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


async def _memory_update_importance(args: dict) -> dict:
    try:
        success = await update_memory_importance(
            args["agent_id"], args["memory_id"], args["importance"]
        )
        return {
            "success": success,
            "data": {"updated": success},
            "error": None if success else "Memory not found or access denied",
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _memory_delete(args: dict) -> dict:
    try:
        success = await delete_memory(args["agent_id"], args["memory_id"])
        if success:
            await get_bus().emit(memory_deleted(args["agent_id"], args["memory_id"]))
        return {
            "success": success,
            "data": {"deleted": success},
            "error": None if success else "Memory not found or access denied",
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
