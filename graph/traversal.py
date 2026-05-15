"""
Graph Traversal — Recursive CTE queries for the three core use cases.

1. find_related_problems(goal_id) — what blocks this goal?
2. impact_analysis(node_id)      — what does deleting this affect?
3. find_required_skills(task_id) — what skills does this task need?
4. find_path(source, target)     — how are two nodes related?
5. get_neighbors(node_id)        — direct neighbors
6. get_subgraph(node_ids)        — subgraph for snapshot context
"""

import sqlite3
from typing import Optional

from database import DB_PATH
from graph.schema import EdgeType, NodeType


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Use Case 1: What problems are related to this goal? ──────────────────────

def find_related_problems(
    agent_id: str,
    goal_node_id: str,
    max_depth: int = 4,
    db_path: str = DB_PATH
) -> list[dict]:
    """
    Starting from a goal, walk BACKWARDS to find what blocks or causes
    problems for it. Returns nodes with their path to the goal.

    Example:
      Memory A ──causes──▶ Problem B ──blocks──▶ Goal C
      → returns [Memory A, Problem B] with path info
    """
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE backwards(node_id, path, depth, edge_chain) AS (
                -- Seed: nodes that directly affect the goal
                SELECT
                    e.source_node_id,
                    n.label,
                    1,
                    e.edge_type
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.source_node_id
                WHERE e.agent_id = ?
                  AND e.target_node_id = ?
                  AND e.edge_type IN ('blocks','causes','depends_on','requires')

                UNION ALL

                -- Recurse: go further back
                SELECT
                    e.source_node_id,
                    bw.path || ' → ' || n.label,
                    bw.depth + 1,
                    e.edge_type || ' → ' || bw.edge_chain
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.source_node_id
                JOIN backwards bw ON bw.node_id = e.target_node_id
                WHERE e.agent_id = ?
                  AND e.edge_type IN ('blocks','causes','depends_on','requires')
                  AND bw.depth < ?
            )
            SELECT DISTINCT
                n.*,
                bw.path,
                bw.depth,
                bw.edge_chain
            FROM backwards bw
            JOIN thought_nodes n ON n.id = bw.node_id
            WHERE n.agent_id = ?
            ORDER BY bw.depth ASC, n.node_type
            """,
            (agent_id, goal_node_id, agent_id, max_depth, agent_id)
        ).fetchall()

        return [
            {**dict(r), "hops_to_goal": r["depth"], "path": r["path"]}
            for r in rows
        ]
    finally:
        conn.close()


# ── Use Case 2: Impact analysis — what does deleting this node affect? ────────

def impact_analysis(
    agent_id: str,
    node_id: str,
    max_depth: int = 5,
    db_path: str = DB_PATH
) -> dict:
    """
    Starting from a node, walk FORWARD to find everything that depends on it.
    Returns a structured impact report.

    Example:
      Memory A ──causes──▶ Problem B ──blocks──▶ Goal C
      Deleting Memory A → Problem B may disappear → Goal C may unblock
    """
    conn = _conn(db_path)
    try:
        # Get the source node
        source = conn.execute(
            "SELECT * FROM thought_nodes WHERE id = ? AND agent_id = ?",
            (node_id, agent_id)
        ).fetchone()

        if not source:
            return {"error": "Node not found"}

        # Forward traversal
        rows = conn.execute(
            """
            WITH RECURSIVE forwards(node_id, path, depth, edge_chain, cumulative_weight) AS (
                SELECT
                    e.target_node_id,
                    n.label,
                    1,
                    e.edge_type,
                    e.weight
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                WHERE e.agent_id = ?
                  AND e.source_node_id = ?

                UNION ALL

                SELECT
                    e.target_node_id,
                    fw.path || ' → ' || n.label,
                    fw.depth + 1,
                    fw.edge_chain || ' → ' || e.edge_type,
                    fw.cumulative_weight * e.weight
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                JOIN forwards fw ON fw.node_id = e.source_node_id
                WHERE e.agent_id = ?
                  AND fw.depth < ?
                  AND e.target_node_id != ?
            )
            SELECT DISTINCT
                n.*,
                fw.path,
                fw.depth,
                fw.edge_chain,
                fw.cumulative_weight
            FROM forwards fw
            JOIN thought_nodes n ON n.id = fw.node_id
            WHERE n.agent_id = ?
            ORDER BY fw.depth ASC, fw.cumulative_weight DESC
            """,
            (agent_id, node_id, agent_id, max_depth, node_id, agent_id)
        ).fetchall()

        affected = [dict(r) for r in rows]

        # Group by node type for the impact report
        by_type: dict[str, list] = {}
        for node in affected:
            t = node["node_type"]
            by_type.setdefault(t, []).append(node)

        # Severity: goals and skills are critical
        critical = [n for n in affected if n["node_type"] in (NodeType.GOAL, NodeType.SKILL)]
        blocking = [n for n in affected if n["node_type"] == NodeType.PROBLEM]

        severity = "low"
        if critical:
            severity = "critical"
        elif blocking:
            severity = "medium"

        return {
            "source_node": dict(source),
            "total_affected": len(affected),
            "severity": severity,
            "affected_by_type": by_type,
            "critical_nodes": critical,
            "summary": (
                f"حذف هذه العقدة سيؤثر على {len(affected)} عقدة، "
                f"منها {len(critical)} هدف/مهارة حرجة."
            ) if affected else "لا توجد تبعيات مباشرة لهذه العقدة."
        }
    finally:
        conn.close()


# ── Use Case 3: What skills does this task require? ───────────────────────────

def find_required_skills(
    agent_id: str,
    task_node_id: str,
    max_depth: int = 4,
    db_path: str = DB_PATH
) -> list[dict]:
    """
    Find all skill nodes reachable from a task via any path.
    Includes direct requires edges and indirect paths through episodes.

    Example:
      Task ──requires──▶ Skill D  (direct)
      Task ──relates_to──▶ Episode ──learned_from──▶ Skill D  (indirect)
    """
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE skill_search(node_id, path, depth, edge_chain) AS (
                SELECT
                    e.target_node_id,
                    n.label,
                    1,
                    e.edge_type
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                WHERE e.agent_id = ?
                  AND e.source_node_id = ?

                UNION ALL

                SELECT
                    e.target_node_id,
                    ss.path || ' → ' || n.label,
                    ss.depth + 1,
                    ss.edge_chain || ' → ' || e.edge_type
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                JOIN skill_search ss ON ss.node_id = e.source_node_id
                WHERE e.agent_id = ?
                  AND ss.depth < ?
                  AND e.target_node_id != ?
            )
            SELECT DISTINCT n.*, ss.path, ss.depth, ss.edge_chain
            FROM skill_search ss
            JOIN thought_nodes n ON n.id = ss.node_id
            WHERE n.agent_id = ?
              AND n.node_type = 'skill'
            ORDER BY ss.depth ASC
            """,
            (agent_id, task_node_id, agent_id, max_depth, task_node_id, agent_id)
        ).fetchall()

        return [{**dict(r), "hops": r["depth"]} for r in rows]
    finally:
        conn.close()


# ── Path Finding — how are two nodes related? ─────────────────────────────────

def find_path(
    agent_id: str,
    source_node_id: str,
    target_node_id: str,
    max_depth: int = 6,
    db_path: str = DB_PATH
) -> Optional[dict]:
    """
    Find the shortest path between two nodes.
    Returns the path with edge labels or None if no path exists.
    """
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE pathfind(node_id, path_nodes, path_edges, depth) AS (
                SELECT
                    e.target_node_id,
                    ? || ' → ' || n.label,
                    e.edge_type,
                    1
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                WHERE e.agent_id = ? AND e.source_node_id = ?

                UNION ALL

                SELECT
                    e.target_node_id,
                    pf.path_nodes || ' → ' || n.label,
                    pf.path_edges || ' / ' || e.edge_type,
                    pf.depth + 1
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                JOIN pathfind pf ON pf.node_id = e.source_node_id
                WHERE e.agent_id = ?
                  AND pf.depth < ?
                  AND pf.path_nodes NOT LIKE '%' || n.label || '%'
            )
            SELECT path_nodes, path_edges, depth
            FROM pathfind
            WHERE node_id = ?
            ORDER BY depth ASC
            LIMIT 1
            """,
            (
                # get source label
                conn.execute(
                    "SELECT label FROM thought_nodes WHERE id = ?", (source_node_id,)
                ).fetchone()["label"],
                agent_id, source_node_id,
                agent_id, max_depth,
                target_node_id
            )
        ).fetchone()

        if not rows:
            return None

        return {
            "path": rows["path_nodes"],
            "edges": rows["path_edges"],
            "hops": rows["depth"],
        }
    finally:
        conn.close()


# ── Neighbors — direct connections ────────────────────────────────────────────

def get_neighbors(
    agent_id: str,
    node_id: str,
    direction: str = "both",
    edge_types: Optional[list] = None,
    db_path: str = DB_PATH
) -> dict:
    """Return direct neighbors with their edge types."""
    conn = _conn(db_path)
    try:
        outgoing, incoming = [], []

        if direction in ("out", "both"):
            params: list = [agent_id, node_id]
            q = """
                SELECT n.*, e.edge_type, e.weight, e.description as edge_desc
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.target_node_id
                WHERE e.agent_id = ? AND e.source_node_id = ?
            """
            if edge_types:
                q += f" AND e.edge_type IN ({','.join('?'*len(edge_types))})"
                params += edge_types
            outgoing = [dict(r) for r in conn.execute(q, params).fetchall()]

        if direction in ("in", "both"):
            params = [agent_id, node_id]
            q = """
                SELECT n.*, e.edge_type, e.weight, e.description as edge_desc
                FROM thought_edges e
                JOIN thought_nodes n ON n.id = e.source_node_id
                WHERE e.agent_id = ? AND e.target_node_id = ?
            """
            if edge_types:
                q += f" AND e.edge_type IN ({','.join('?'*len(edge_types))})"
                params += edge_types
            incoming = [dict(r) for r in conn.execute(q, params).fetchall()]

        return {"outgoing": outgoing, "incoming": incoming}
    finally:
        conn.close()


# ── Subgraph for snapshot context ─────────────────────────────────────────────

def get_context_subgraph(
    agent_id: str,
    node_ids: list[str],
    db_path: str = DB_PATH
) -> dict:
    """
    Given a list of node IDs (e.g. from active goals + recent memories),
    return all nodes and edges that connect them.
    Used by context_get_snapshot to enrich the cognitive state.
    """
    if not node_ids:
        return {"nodes": [], "edges": []}

    conn = _conn(db_path)
    try:
        placeholders = ",".join("?" * len(node_ids))

        nodes = conn.execute(
            f"SELECT * FROM thought_nodes WHERE id IN ({placeholders}) AND agent_id = ?",
            node_ids + [agent_id]
        ).fetchall()

        edges = conn.execute(
            f"""
            SELECT * FROM thought_edges
            WHERE agent_id = ?
              AND source_node_id IN ({placeholders})
              AND target_node_id IN ({placeholders})
            """,
            [agent_id] + node_ids + node_ids
        ).fetchall()

        return {
            "nodes": [dict(n) for n in nodes],
            "edges": [dict(e) for e in edges],
        }
    finally:
        conn.close()
