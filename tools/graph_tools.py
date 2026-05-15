"""
MCP Tool Definitions — Thought Graph

8 tools covering:
  - Manual graph building (add_node, add_edge, delete)
  - The 3 core use cases (related_problems, impact_analysis, required_skills)
  - Discovery (find_path, get_neighbors)
  - LLM auto-extraction (extract_from_text)

Exports:
    TOOL_SCHEMAS: list of Tool dicts for list_tools()
    handle_graph_tool(name, args): async dispatcher for call_tool()
"""

from typing import Optional

from graph.store import (
    add_node, add_edge, get_node,
    find_nodes, delete_node, delete_edge,
    get_edges, graph_stats,
)
from graph.traversal import (
    find_related_problems,
    impact_analysis,
    find_required_skills,
    find_path,
    get_neighbors,
)
from graph.extractor import extract_from_text, extract_relationship
from graph.schema import NodeType, EdgeType


TOOL_SCHEMAS = [
    {
        "name": "graph_add_node",
        "description": (
            "Add a node to the thought graph.\n"
            "node_type: memory | goal | problem | skill | episode | concept | task\n"
            "label: short name (2-5 words)\n"
            "description: one sentence explaining this node\n"
            "ref_id: optional ID linking to memories/goals/reflection_logs table"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_type": {"type": "string", "description": "memory | goal | problem | skill | episode | concept | task"},
                "label": {"type": "string", "description": "Short name (2-5 words)"},
                "description": {"type": "string", "description": "One sentence explaining this node", "default": ""},
                "ref_id": {"type": "string", "description": "Optional ID linking to other tables", "default": None},
            },
            "required": ["agent_id", "node_type", "label"],
        },
    },
    {
        "name": "graph_add_edge",
        "description": (
            "Add a directed edge between two nodes.\n"
            "edge_type: causes | blocks | requires | learned_from | solves | "
            "depends_on | enables | contradicts | relates_to\n"
            "weight: confidence 0.0–1.0 (default 0.8)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "source_node_id": {"type": "string", "description": "Source node ID"},
                "edge_type": {"type": "string", "description": "causes | blocks | requires | learned_from | solves | depends_on | enables | contradicts | relates_to"},
                "target_node_id": {"type": "string", "description": "Target node ID"},
                "weight": {"type": "number", "description": "Confidence 0.0-1.0", "default": 0.8},
                "description": {"type": "string", "description": "Optional description", "default": ""},
            },
            "required": ["agent_id", "source_node_id", "edge_type", "target_node_id"],
        },
    },
    {
        "name": "graph_find_nodes",
        "description": (
            "Search for nodes in the graph. "
            "Use before adding edges to get node IDs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_type": {"type": "string", "description": "Filter by node type", "default": None},
                "label_contains": {"type": "string", "description": "Filter by label content", "default": None},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "graph_delete_node",
        "description": "Delete a node and all its edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_id": {"type": "string", "description": "Node ID to delete"},
            },
            "required": ["agent_id", "node_id"],
        },
    },
    {
        "name": "graph_stats",
        "description": "Return statistics about the thought graph (node/edge counts by type).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "graph_find_related_problems",
        "description": (
            "USE CASE 1: What is blocking or causing problems for this goal?\n"
            "Walks BACKWARDS from the goal to find all nodes that directly "
            "or indirectly block/cause issues for it. "
            "Returns nodes with their path to the goal and hop count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "goal_node_id": {"type": "string", "description": "Goal node ID to analyze"},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "default": 4},
            },
            "required": ["agent_id", "goal_node_id"],
        },
    },
    {
        "name": "graph_impact_analysis",
        "description": (
            "USE CASE 2: What will be affected if this node is deleted or changed?\n"
            "Walks FORWARD from the node to find everything that depends on it. "
            "Returns a severity report: low / medium / critical. "
            "Use this BEFORE deleting any important memory or node."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_id": {"type": "string", "description": "Node ID to analyze"},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "default": 5},
            },
            "required": ["agent_id", "node_id"],
        },
    },
    {
        "name": "graph_find_required_skills",
        "description": (
            "USE CASE 3: What skills are needed to complete this task?\n"
            "Finds all skill nodes reachable from the task via any path. "
            "Includes both direct (task ──requires──▶ skill) and "
            "indirect paths (task → episode ──learned_from──▶ skill). "
            "Returns skills sorted by proximity (direct requirements first)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "task_node_id": {"type": "string", "description": "Task node ID to analyze"},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "default": 4},
            },
            "required": ["agent_id", "task_node_id"],
        },
    },
    {
        "name": "graph_find_path",
        "description": (
            "Find the shortest path between two nodes. "
            "Useful for understanding how two concepts are related."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "source_node_id": {"type": "string", "description": "Source node ID"},
                "target_node_id": {"type": "string", "description": "Target node ID"},
                "max_depth": {"type": "integer", "description": "Max traversal depth", "default": 6},
            },
            "required": ["agent_id", "source_node_id", "target_node_id"],
        },
    },
    {
        "name": "graph_get_neighbors",
        "description": (
            "Get direct neighbors of a node.\n"
            "direction: 'out' (what this node affects) | "
            "'in' (what affects this node) | 'both' (all connections)\n"
            "edge_types: optional filter, e.g. ['causes', 'blocks']"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_id": {"type": "string", "description": "Node ID"},
                "direction": {"type": "string", "description": "out | in | both", "default": "both"},
                "edge_types": {"type": "array", "items": {"type": "string"}, "description": "Optional edge type filter", "default": []},
            },
            "required": ["agent_id", "node_id"],
        },
    },
    {
        "name": "graph_extract_from_text",
        "description": (
            "AUTO-EXTRACT: Use the LLM to automatically identify nodes and edges "
            "from any text (memory content, reflection log, notes, etc.)\n"
            "The LLM will:\n"
            "1. Identify key concepts, problems, skills, and goals in the text\n"
            "2. Determine relationships between them\n"
            "3. Add them to the thought graph automatically\n\n"
            "Use after storing important memories or reflection logs.\n"
            "context: helps the LLM understand what type of text this is"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "text": {"type": "string", "description": "Text to extract from"},
                "context": {"type": "string", "description": "Context hint for the LLM", "default": ""},
                "source_ref_id": {"type": "string", "description": "Optional source reference ID", "default": None},
            },
            "required": ["agent_id", "text"],
        },
    },
    {
        "name": "graph_extract_relationship",
        "description": (
            "Ask the LLM: what is the relationship between concept A and concept B?\n"
            "Useful when you know two things are related but aren't sure how. "
            "The LLM will suggest the edge type and confidence weight."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID"},
                "node_a_label": {"type": "string", "description": "First concept label"},
                "node_b_label": {"type": "string", "description": "Second concept label"},
                "context": {"type": "string", "description": "Optional context", "default": ""},
            },
            "required": ["agent_id", "node_a_label", "node_b_label"],
        },
    },
]


async def handle_graph_tool(name: str, args: dict) -> dict:
    """Dispatch graph tool call to the appropriate handler."""
    handlers = {
        "graph_add_node": _graph_add_node,
        "graph_add_edge": _graph_add_edge,
        "graph_find_nodes": _graph_find_nodes,
        "graph_delete_node": _graph_delete_node,
        "graph_stats": _graph_stats,
        "graph_find_related_problems": _graph_find_related_problems,
        "graph_impact_analysis": _graph_impact_analysis,
        "graph_find_required_skills": _graph_find_required_skills,
        "graph_find_path": _graph_find_path,
        "graph_get_neighbors": _graph_get_neighbors,
        "graph_extract_from_text": _graph_extract_from_text,
        "graph_extract_relationship": _graph_extract_relationship,
    }
    handler = handlers.get(name)
    if handler is None:
        return {"success": False, "data": None, "error": f"Unknown graph tool: {name}"}
    return await handler(args)


async def _graph_add_node(args: dict) -> dict:
    try:
        node = add_node(
            agent_id=args["agent_id"],
            node_type=args["node_type"],
            label=args["label"],
            description=args.get("description", ""),
            ref_id=args.get("ref_id"),
            source="manual",
        )
        return {"success": True, "data": node, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_add_edge(args: dict) -> dict:
    try:
        edge = add_edge(
            agent_id=args["agent_id"],
            source_node_id=args["source_node_id"],
            edge_type=args["edge_type"],
            target_node_id=args["target_node_id"],
            weight=args.get("weight", 0.8),
            description=args.get("description", ""),
            source="manual",
        )
        return {"success": True, "data": edge, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_find_nodes(args: dict) -> dict:
    try:
        nodes = find_nodes(
            agent_id=args["agent_id"],
            node_type=args.get("node_type"),
            label_contains=args.get("label_contains"),
            limit=args.get("limit", 20),
        )
        return {"success": True, "data": nodes, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


async def _graph_delete_node(args: dict) -> dict:
    try:
        deleted = delete_node(node_id=args["node_id"], agent_id=args["agent_id"])
        return {
            "success": deleted,
            "data": {"deleted": deleted},
            "error": None if deleted else "Node not found",
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_stats(args: dict) -> dict:
    try:
        stats = graph_stats(agent_id=args["agent_id"])
        return {"success": True, "data": stats, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_find_related_problems(args: dict) -> dict:
    try:
        nodes = find_related_problems(
            agent_id=args["agent_id"],
            goal_node_id=args["goal_node_id"],
            max_depth=args.get("max_depth", 4),
        )
        return {
            "success": True,
            "data": {
                "goal_node_id": args["goal_node_id"],
                "blocking_nodes": nodes,
                "total_found": len(nodes),
                "summary": (
                    f"وجدت {len(nodes)} عقدة تؤثر على هذا الهدف."
                    if nodes else "لا توجد مشاكل مرتبطة بهذا الهدف في الـ graph."
                ),
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_impact_analysis(args: dict) -> dict:
    try:
        result = impact_analysis(
            agent_id=args["agent_id"],
            node_id=args["node_id"],
            max_depth=args.get("max_depth", 5),
        )
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_find_required_skills(args: dict) -> dict:
    try:
        skills = find_required_skills(
            agent_id=args["agent_id"],
            task_node_id=args["task_node_id"],
            max_depth=args.get("max_depth", 4),
        )
        return {
            "success": True,
            "data": {
                "task_node_id": args["task_node_id"],
                "required_skills": skills,
                "total_found": len(skills),
                "direct": [s for s in skills if s.get("hops", 0) == 1],
                "indirect": [s for s in skills if s.get("hops", 0) > 1],
            },
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_find_path(args: dict) -> dict:
    try:
        path = find_path(
            agent_id=args["agent_id"],
            source_node_id=args["source_node_id"],
            target_node_id=args["target_node_id"],
            max_depth=args.get("max_depth", 6),
        )
        return {
            "success": True,
            "data": path or {"message": "لا يوجد مسار بين هاتين العقدتين"},
            "error": None,
        }
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_get_neighbors(args: dict) -> dict:
    edge_types = args.get("edge_types", [])
    try:
        neighbors = get_neighbors(
            agent_id=args["agent_id"],
            node_id=args["node_id"],
            direction=args.get("direction", "both"),
            edge_types=edge_types if edge_types else None,
        )
        return {"success": True, "data": neighbors, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_extract_from_text(args: dict) -> dict:
    try:
        result = await extract_from_text(
            text=args["text"],
            agent_id=args["agent_id"],
            context=args.get("context", ""),
            source_ref_id=args.get("source_ref_id"),
        )
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}


async def _graph_extract_relationship(args: dict) -> dict:
    try:
        result = await extract_relationship(
            agent_id=args["agent_id"],
            node_a_label=args["node_a_label"],
            node_b_label=args["node_b_label"],
            context=args.get("context", ""),
        )
        if not result:
            return {"success": False, "data": None, "error": "Could not determine relationship"}
        return {"success": True, "data": result, "error": None}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e)}
