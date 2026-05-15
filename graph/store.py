"""
Graph Store — CRUD operations for nodes and edges.
All sync (daemon + gateway compatible).
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from database import DB_PATH
from graph.schema import NodeType, EdgeType


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Nodes ─────────────────────────────────────────────────────────────────────

def add_node(
    agent_id: str,
    node_type: str,
    label: str,
    description: str = "",
    ref_id: Optional[str] = None,
    source: str = "manual",
    db_path: str = DB_PATH
) -> dict:
    """
    Add a node. Returns the node dict.
    If a node with same agent_id + node_type + label exists, returns it (upsert).
    """
    if node_type not in NodeType.ALL:
        raise ValueError(f"Invalid node_type '{node_type}'. Must be one of {NodeType.ALL}")

    conn = _conn(db_path)
    now = _now()
    try:
        # Check for existing node with same identity
        existing = conn.execute(
            """
            SELECT * FROM thought_nodes
            WHERE agent_id = ? AND node_type = ? AND label = ?
            """,
            (agent_id, node_type, label)
        ).fetchone()

        if existing:
            # Update description if provided
            if description:
                conn.execute(
                    "UPDATE thought_nodes SET description = ?, updated_at = ? WHERE id = ?",
                    (description, now, existing["id"])
                )
                conn.commit()
            return dict(existing)

        node_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO thought_nodes
            (id, agent_id, node_type, label, description, ref_id, created_at, updated_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (node_id, agent_id, node_type, label, description, ref_id, now, now, source)
        )
        conn.commit()
        return {
            "id": node_id, "agent_id": agent_id, "node_type": node_type,
            "label": label, "description": description, "ref_id": ref_id,
            "created_at": now, "source": source
        }
    finally:
        conn.close()


def get_node(node_id: str, agent_id: str, db_path: str = DB_PATH) -> Optional[dict]:
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM thought_nodes WHERE id = ? AND agent_id = ?",
            (node_id, agent_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_nodes(
    agent_id: str,
    node_type: Optional[str] = None,
    label_contains: Optional[str] = None,
    limit: int = 20,
    db_path: str = DB_PATH
) -> list[dict]:
    conn = _conn(db_path)
    try:
        conditions = ["agent_id = ?"]
        params: list = [agent_id]

        if node_type:
            conditions.append("node_type = ?")
            params.append(node_type)
        if label_contains:
            conditions.append("label LIKE ?")
            params.append(f"%{label_contains}%")

        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM thought_nodes WHERE {' AND '.join(conditions)} "
            f"ORDER BY updated_at DESC LIMIT ?",
            params
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_node(node_id: str, agent_id: str, db_path: str = DB_PATH) -> bool:
    """Delete a node and all its edges (CASCADE)."""
    conn = _conn(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM thought_nodes WHERE id = ? AND agent_id = ?",
            (node_id, agent_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ── Edges ─────────────────────────────────────────────────────────────────────

def add_edge(
    agent_id: str,
    source_node_id: str,
    edge_type: str,
    target_node_id: str,
    weight: float = 0.8,
    description: str = "",
    source: str = "manual",
    db_path: str = DB_PATH
) -> dict:
    """
    Add a directed edge. Upserts on (agent, source, target, type).
    Returns the edge dict.
    """
    if edge_type not in EdgeType.ALL:
        raise ValueError(f"Invalid edge_type '{edge_type}'. Must be one of {EdgeType.ALL}")

    conn = _conn(db_path)
    now = _now()
    try:
        # Verify both nodes belong to this agent
        for nid in (source_node_id, target_node_id):
            row = conn.execute(
                "SELECT id FROM thought_nodes WHERE id = ? AND agent_id = ?",
                (nid, agent_id)
            ).fetchone()
            if not row:
                raise ValueError(f"Node {nid} not found for agent {agent_id}")

        edge_id = str(uuid.uuid4())
        try:
            conn.execute(
                """
                INSERT INTO thought_edges
                (id, agent_id, source_node_id, target_node_id, edge_type,
                 weight, description, created_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (edge_id, agent_id, source_node_id, target_node_id,
                 edge_type, weight, description, now, source)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Duplicate — update weight if higher confidence
            conn.execute(
                """
                UPDATE thought_edges
                SET weight = MAX(weight, ?), description = ?, source = ?
                WHERE agent_id = ? AND source_node_id = ?
                  AND target_node_id = ? AND edge_type = ?
                """,
                (weight, description, source, agent_id,
                 source_node_id, target_node_id, edge_type)
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT * FROM thought_edges
                WHERE agent_id = ? AND source_node_id = ?
                  AND target_node_id = ? AND edge_type = ?
                """,
                (agent_id, source_node_id, target_node_id, edge_type)
            ).fetchone()
            return dict(row)

        return {
            "id": edge_id, "agent_id": agent_id,
            "source_node_id": source_node_id, "target_node_id": target_node_id,
            "edge_type": edge_type, "weight": weight,
            "description": description, "created_at": now, "source": source
        }
    finally:
        conn.close()


def get_edges(
    agent_id: str,
    node_id: str,
    direction: str = "both",    # "out" | "in" | "both"
    edge_types: Optional[list] = None,
    db_path: str = DB_PATH
) -> list[dict]:
    """Get all edges connected to a node."""
    conn = _conn(db_path)
    try:
        results = []

        if direction in ("out", "both"):
            params: list = [agent_id, node_id]
            q = "SELECT * FROM thought_edges WHERE agent_id = ? AND source_node_id = ?"
            if edge_types:
                q += f" AND edge_type IN ({','.join('?'*len(edge_types))})"
                params += edge_types
            rows = conn.execute(q, params).fetchall()
            results += [dict(r) for r in rows]

        if direction in ("in", "both"):
            params = [agent_id, node_id]
            q = "SELECT * FROM thought_edges WHERE agent_id = ? AND target_node_id = ?"
            if edge_types:
                q += f" AND edge_type IN ({','.join('?'*len(edge_types))})"
                params += edge_types
            rows = conn.execute(q, params).fetchall()
            results += [dict(r) for r in rows]

        return results
    finally:
        conn.close()


def delete_edge(edge_id: str, agent_id: str, db_path: str = DB_PATH) -> bool:
    conn = _conn(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM thought_edges WHERE id = ? AND agent_id = ?",
            (edge_id, agent_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def graph_stats(agent_id: str, db_path: str = DB_PATH) -> dict:
    conn = _conn(db_path)
    try:
        nodes = conn.execute(
            "SELECT node_type, COUNT(*) as cnt FROM thought_nodes "
            "WHERE agent_id = ? GROUP BY node_type",
            (agent_id,)
        ).fetchall()
        edges = conn.execute(
            "SELECT edge_type, COUNT(*) as cnt FROM thought_edges "
            "WHERE agent_id = ? GROUP BY edge_type",
            (agent_id,)
        ).fetchall()
        return {
            "nodes": {r["node_type"]: r["cnt"] for r in nodes},
            "edges": {r["edge_type"]: r["cnt"] for r in edges},
            "total_nodes": sum(r["cnt"] for r in nodes),
            "total_edges": sum(r["cnt"] for r in edges),
        }
    finally:
        conn.close()
