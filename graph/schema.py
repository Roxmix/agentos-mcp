"""
Thought Graph — Schema & Constants

Nodes = ideas, memories, goals, problems, skills, episodes
Edges = typed relationships between nodes

SQLite stores the graph.
Recursive CTEs handle traversal.
"""


# ── Node Types ────────────────────────────────────────────────────────────────

class NodeType:
    MEMORY  = "memory"    # linked to memories table
    GOAL    = "goal"      # linked to goals table
    PROBLEM = "problem"   # a discovered problem
    SKILL   = "skill"     # an acquired capability
    EPISODE = "episode"   # linked to reflection_logs
    CONCEPT = "concept"   # abstract idea
    TASK    = "task"      # a specific task

    ALL = [MEMORY, GOAL, PROBLEM, SKILL, EPISODE, CONCEPT, TASK]


# ── Edge Types ────────────────────────────────────────────────────────────────

class EdgeType:
    CAUSES       = "causes"         # A causes B
    BLOCKS       = "blocks"         # A blocks B
    REQUIRES     = "requires"       # A requires B
    LEARNED_FROM = "learned_from"   # A learned from B
    SOLVES       = "solves"         # A solves B
    DEPENDS_ON   = "depends_on"     # A depends on B
    ENABLES      = "enables"        # A enables B
    CONTRADICTS  = "contradicts"    # A contradicts B
    RELATES_TO   = "relates_to"     # generic

    ALL = [
        CAUSES, BLOCKS, REQUIRES, LEARNED_FROM,
        SOLVES, DEPENDS_ON, ENABLES, CONTRADICTS, RELATES_TO
    ]

    # Edges that indicate negative / blocking relationships
    NEGATIVE = [BLOCKS, CONTRADICTS]

    # Edges that indicate dependency
    DEPENDENCY = [REQUIRES, DEPENDS_ON, BLOCKS]


# ── SQL Schema ────────────────────────────────────────────────────────────────

INIT_SQL = """
CREATE TABLE IF NOT EXISTS thought_nodes (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    node_type   TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT DEFAULT '',
    ref_id      TEXT,           -- FK to memories / goals / reflection_logs
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    source      TEXT DEFAULT 'manual'  -- 'manual' | 'auto_llm'
);
CREATE INDEX IF NOT EXISTS idx_tnodes_agent    ON thought_nodes(agent_id);
CREATE INDEX IF NOT EXISTS idx_tnodes_type     ON thought_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_tnodes_ref      ON thought_nodes(ref_id);

CREATE TABLE IF NOT EXISTS thought_edges (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL,
    source_node_id TEXT NOT NULL REFERENCES thought_nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES thought_nodes(id) ON DELETE CASCADE,
    edge_type      TEXT NOT NULL,
    weight         REAL DEFAULT 0.8,   -- 0.0–1.0 confidence
    description    TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    source         TEXT DEFAULT 'manual'  -- 'manual' | 'auto_llm'
);
CREATE INDEX IF NOT EXISTS idx_tedges_agent  ON thought_edges(agent_id);
CREATE INDEX IF NOT EXISTS idx_tedges_source ON thought_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_tedges_target ON thought_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_tedges_type   ON thought_edges(edge_type);

-- Prevent duplicate edges between same pair with same type
CREATE UNIQUE INDEX IF NOT EXISTS idx_tedges_unique
    ON thought_edges(agent_id, source_node_id, target_node_id, edge_type);
"""


def init_graph(conn):
    """Initialize graph tables. Pass an open sqlite3 connection."""
    conn.executescript(INIT_SQL)
    conn.commit()
