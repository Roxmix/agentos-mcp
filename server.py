"""
AgentOS MCP Server - Entry Point

Usage:
    python server.py

Connects via stdio (default MCP transport).
Compatible with Claude Desktop, Hermes, and any MCP-compatible agent.

MCP SDK 1.27+ API: @app.list_tools() + @app.call_tool() decorators
Tool modules export TOOL_SCHEMAS + handle_*_tool() dispatchers.
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

from config import settings
from database import init_db
from tools.memory_tools import TOOL_SCHEMAS as MEMORY_SCHEMAS, handle_memory_tool
from tools.goal_tools import TOOL_SCHEMAS as GOAL_SCHEMAS, handle_goal_tool
from tools.reflection_tools import TOOL_SCHEMAS as REFLECTION_SCHEMAS, handle_reflection_tool
from tools.context_tools import TOOL_SCHEMAS as CONTEXT_SCHEMAS, handle_context_tool
from tools.approval_tools import TOOL_SCHEMAS as APPROVAL_SCHEMAS, handle_approval_tool
from tools.graph_tools import TOOL_SCHEMAS as GRAPH_SCHEMAS, handle_graph_tool

logger = logging.getLogger(__name__)

app = Server(settings.agentos_server_name)

# Collect all tool schemas
ALL_TOOL_SCHEMAS = []
ALL_TOOL_SCHEMAS.extend(MEMORY_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(GOAL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(REFLECTION_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(CONTEXT_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(APPROVAL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(GRAPH_SCHEMAS)

# Dispatch table: tool_name -> handler function
TOOL_HANDLERS = {}
for schema in ALL_TOOL_SCHEMAS:
    name = schema["name"]
    if name.startswith("memory_"):
        TOOL_HANDLERS[name] = lambda args, n=name: handle_memory_tool(n, args)
    elif name.startswith("goal_"):
        TOOL_HANDLERS[name] = lambda args, n=name: handle_goal_tool(n, args)
    elif name.startswith("reflection_"):
        TOOL_HANDLERS[name] = lambda args, n=name: handle_reflection_tool(n, args)
    elif name.startswith("approval_"):
        TOOL_HANDLERS[name] = lambda args, n=name: handle_approval_tool(n, args)
    elif name.startswith("graph_"):
        TOOL_HANDLERS[name] = lambda args, n=name: handle_graph_tool(n, args)
    elif name == "context_get_snapshot":
        TOOL_HANDLERS[name] = lambda args, n=name: handle_context_tool(n, args)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return all available AgentOS tools."""
    return [Tool(**schema) for schema in ALL_TOOL_SCHEMAS]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    """Dispatch tool call to the appropriate handler."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Unknown tool: {name}"
            }))]
        )
    try:
        result = await handler(arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))]
        )
    except Exception as e:
        logger.exception(f"Error calling tool {name}")
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps({
                "success": False,
                "error": str(e)
            }))]
        )


async def _run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


def main():
    init_db()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
