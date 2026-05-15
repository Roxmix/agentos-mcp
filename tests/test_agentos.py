"""Basic smoke tests for AgentOS MCP Server."""
import asyncio
import json
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.mark.asyncio
async def test_list_tools():
    """All 31 tools should be registered."""
    from server import list_tools
    tools = await list_tools()
    assert len(tools) == 31


@pytest.mark.asyncio
async def test_tool_names():
    """All expected tool names should be present."""
    from server import list_tools
    tools = await list_tools()
    names = {t.name for t in tools}
    expected = {
        "memory_store", "memory_search", "memory_list",
        "memory_update_importance", "memory_delete",
        "goal_add", "goal_get_active", "goal_update_progress",
        "goal_update_status", "goal_list",
        "reflection_log", "reflection_analyze",
        "reflection_get_patterns", "reflection_get_summary",
        "context_get_snapshot",
        "approval_list", "approval_get_details",
        "approval_decide", "approval_history",
        "graph_add_node", "graph_add_edge", "graph_find_nodes",
        "graph_delete_node", "graph_stats",
        "graph_find_related_problems", "graph_impact_analysis",
        "graph_find_required_skills",
        "graph_find_path", "graph_get_neighbors",
        "graph_extract_from_text", "graph_extract_relationship",
    }
    assert names == expected


@pytest.mark.asyncio
async def test_goal_add():
    """goal_add should succeed and return a goal_id."""
    from server import call_tool
    r = await call_tool("goal_add", {
        "agent_id": "test",
        "title": "Test Goal",
        "description": "A test goal"
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True
    assert "id" in data.get("data", {})


@pytest.mark.asyncio
async def test_memory_store():
    """memory_store should succeed and return a memory_id."""
    from server import call_tool
    r = await call_tool("memory_store", {
        "agent_id": "test",
        "content": "Test memory content",
        "memory_type": "semantic",
        "importance": 0.8,
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True
    assert "id" in data.get("data", {})


@pytest.mark.asyncio
async def test_memory_list():
    """memory_list should return stored memories."""
    from server import call_tool
    agent = "test_list_agent"
    await call_tool("memory_store", {
        "agent_id": agent,
        "content": "Memory for list test",
    })
    r = await call_tool("memory_list", {
        "agent_id": agent,
        "limit": 10
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True
    assert len(data.get("data", [])) >= 1


@pytest.mark.asyncio
async def test_reflection_log_and_analyze():
    """reflection_log should accept entries, reflection_analyze should detect patterns."""
    from server import call_tool
    agent = "test_reflect"
    for i in range(3):
        await call_tool("reflection_log", {
            "agent_id": agent,
            "action": "run_tests",
            "outcome": "fail",
            "success": False,
        })
    r = await call_tool("reflection_analyze", {
        "agent_id": agent,
        "lookback_days": 7
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True


@pytest.mark.asyncio
async def test_graph_add_node():
    """graph_add_node should create a node with valid node_type."""
    from server import call_tool
    r = await call_tool("graph_add_node", {
        "agent_id": "test",
        "label": "TestNode",
        "node_type": "concept",
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True


@pytest.mark.asyncio
async def test_context_snapshot():
    """context_get_snapshot should return a unified cognitive state."""
    from server import call_tool
    agent = "test_snapshot"
    await call_tool("memory_store", {
        "agent_id": agent,
        "content": "Snapshot test memory",
    })
    r = await call_tool("context_get_snapshot", {
        "agent_id": agent,
        "include_memories": 5,
        "include_goals": 5,
    })
    data = json.loads(r.content[0].text)
    assert data["success"] is True
    assert "agent_id" in data.get("data", {})


@pytest.mark.asyncio
async def test_unknown_tool():
    """Unknown tool should return success=False."""
    from server import call_tool
    r = await call_tool("nonexistent_tool", {})
    data = json.loads(r.content[0].text)
    assert data["success"] is False
