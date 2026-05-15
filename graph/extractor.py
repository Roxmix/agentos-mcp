"""
LLM Extractor — Automatically extracts nodes and edges from text.

When the agent stores a memory or logs a reflection,
this module calls the LLM to extract:
  - What concepts/entities are in this text?
  - What relationships exist between them?
  - How do they relate to existing nodes in the graph?

Uses Anthropic API directly (model-agnostic via config).
"""

import json
import re
from typing import Optional
from loguru import logger

from graph.schema import NodeType, EdgeType
from graph.store import add_node, add_edge, find_nodes
from database import DB_PATH


# ── Extraction Prompt ─────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge graph extraction engine.
Your job is to extract nodes and edges from text and return ONLY valid JSON.

Node types available: memory, goal, problem, skill, episode, concept, task
Edge types available: causes, blocks, requires, learned_from, solves, depends_on, enables, contradicts, relates_to

Rules:
- Extract only meaningful, non-trivial relationships
- Each node must have: type, label (short 2-5 words), description (1 sentence)
- Each edge must have: source_label, edge_type, target_label, weight (0.0-1.0), description
- Weight reflects confidence in the relationship (0.9 = very sure, 0.5 = possible)
- Return ONLY the JSON object, no explanation, no markdown backticks

Output format (strict JSON):
{
  "nodes": [
    {"type": "problem", "label": "API timeout issue", "description": "HTTP requests exceed 30s timeout"},
    {"type": "skill", "label": "async programming", "description": "Writing non-blocking code"}
  ],
  "edges": [
    {
      "source_label": "API timeout issue",
      "edge_type": "requires",
      "target_label": "async programming",
      "weight": 0.85,
      "description": "Fixing timeouts requires async programming knowledge"
    }
  ]
}"""


async def extract_from_text(
    text: str,
    agent_id: str,
    context: str = "",
    source_ref_id: Optional[str] = None,
    db_path: str = DB_PATH
) -> dict:
    """
    Extract nodes and edges from text using the LLM.
    Persists extracted graph elements to the database.
    Returns summary of what was extracted.

    Args:
        text: The text to analyze (memory content, reflection, etc.)
        agent_id: The agent this belongs to
        context: Optional context (e.g. "this is a reflection log about a failed API call")
        source_ref_id: Optional ref_id to attach to extracted memory nodes
        db_path: Database path
    """
    prompt = f"""Extract knowledge graph nodes and edges from this text.

Context: {context or 'General agent memory/reflection'}

Text to analyze:
\"\"\"
{text[:2000]}
\"\"\"

Return ONLY the JSON object with nodes and edges arrays."""

    try:
        raw = await _call_llm(prompt)
        extracted = _parse_llm_response(raw)
    except Exception as e:
        logger.warning(f"[extractor] LLM call failed: {e}")
        return {"nodes_added": 0, "edges_added": 0, "error": str(e)}

    if not extracted:
        return {"nodes_added": 0, "edges_added": 0}

    # Persist extracted nodes
    label_to_id: dict[str, str] = {}
    nodes_added = 0

    for node_data in extracted.get("nodes", []):
        node_type = node_data.get("type", "concept")
        if node_type not in NodeType.ALL:
            node_type = "concept"

        try:
            node = add_node(
                agent_id=agent_id,
                node_type=node_type,
                label=node_data.get("label", "")[:100],
                description=node_data.get("description", "")[:500],
                ref_id=source_ref_id if node_type == "memory" else None,
                source="auto_llm",
                db_path=db_path
            )
            label_to_id[node["label"]] = node["id"]
            nodes_added += 1
        except Exception as e:
            logger.warning(f"[extractor] failed to add node '{node_data.get('label')}': {e}")

    # Persist extracted edges
    edges_added = 0

    for edge_data in extracted.get("edges", []):
        source_label = edge_data.get("source_label", "")
        target_label = edge_data.get("target_label", "")
        edge_type    = edge_data.get("edge_type", "relates_to")

        if edge_type not in EdgeType.ALL:
            edge_type = "relates_to"

        source_id = label_to_id.get(source_label)
        target_id = label_to_id.get(target_label)

        # If node not in this batch, search existing graph
        if not source_id:
            source_id = _find_node_id(agent_id, source_label, db_path)
        if not target_id:
            target_id = _find_node_id(agent_id, target_label, db_path)

        if not source_id or not target_id:
            logger.debug(
                f"[extractor] skipping edge '{source_label}' → '{target_label}': "
                "one or both nodes not found"
            )
            continue

        try:
            add_edge(
                agent_id=agent_id,
                source_node_id=source_id,
                edge_type=edge_type,
                target_node_id=target_id,
                weight=float(edge_data.get("weight", 0.7)),
                description=edge_data.get("description", ""),
                source="auto_llm",
                db_path=db_path
            )
            edges_added += 1
        except Exception as e:
            logger.warning(f"[extractor] failed to add edge: {e}")

    logger.info(
        f"[extractor] agent={agent_id} "
        f"nodes_added={nodes_added} edges_added={edges_added}"
    )

    return {
        "nodes_added": nodes_added,
        "edges_added": edges_added,
        "node_labels": list(label_to_id.keys()),
    }


async def extract_relationship(
    agent_id: str,
    node_a_label: str,
    node_b_label: str,
    context: str = "",
    db_path: str = DB_PATH
) -> Optional[dict]:
    """
    Ask the LLM: what is the relationship between node A and node B?
    Returns edge dict or None.
    """
    prompt = f"""Given these two concepts:
A: "{node_a_label}"
B: "{node_b_label}"
Context: {context or 'No additional context'}

What is the most accurate relationship from A to B?
Choose one edge type: {', '.join(EdgeType.ALL)}

Return ONLY this JSON:
{{
  "edge_type": "...",
  "weight": 0.0-1.0,
  "description": "one sentence explanation"
}}"""

    try:
        raw = await _call_llm(prompt)
        data = _parse_llm_response(raw)
        if not data or "edge_type" not in data:
            return None

        edge_type = data["edge_type"]
        if edge_type not in EdgeType.ALL:
            return None

        return {
            "edge_type": edge_type,
            "weight": float(data.get("weight", 0.7)),
            "description": data.get("description", ""),
        }
    except Exception as e:
        logger.warning(f"[extractor] relationship extraction failed: {e}")
        return None


# ── LLM Call ──────────────────────────────────────────────────────────────────

async def _call_llm(prompt: str) -> str:
    """Call Anthropic API asynchronously."""
    import httpx

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": EXTRACTION_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }
        )
        resp.raise_for_status()
        data = resp.json()

    # Extract text from response
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]

    raise ValueError("No text content in LLM response")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_llm_response(raw: str) -> Optional[dict]:
    """Parse JSON from LLM response, handling common formatting issues."""
    if not raw:
        return None

    # Strip markdown code blocks if present
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON object within the text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    logger.warning(f"[extractor] could not parse LLM response: {raw[:200]}")
    return None


def _find_node_id(agent_id: str, label: str, db_path: str) -> Optional[str]:
    """Search for an existing node by label (fuzzy)."""
    nodes = find_nodes(
        agent_id=agent_id,
        label_contains=label[:20],  # first 20 chars
        limit=1,
        db_path=db_path
    )
    return nodes[0]["id"] if nodes else None
