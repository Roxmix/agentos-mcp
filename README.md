# AgentOS — Persistent Cognitive Layer for AI Agents

AgentOS is an **MCP (Model Context Protocol) server** that gives any compatible AI agent a persistent cognitive layer: long-term memory, goal tracking, self-reflection, and autonomous background monitoring.

It is **not** a standalone agent. It is a skill that agents like Claude Code, Hermes, or any MCP-compatible agent can connect to and use.

```
Without AgentOS:   Agent ←→ Tools
With AgentOS:      Agent ←→ AgentOS (Memory · Goals · Reflection · Insights) ←→ Tools
```

---

## Features

- **Persistent Memory** — semantic search across sessions using local embeddings (no API needed)
- **Goal Management** — track objectives with priority, urgency, deadlines, and progress
- **Self-Reflection** — log actions and outcomes, detect repeated failures and success patterns
- **Background Daemon** — runs independently, monitors agents, and generates proactive insights
- **Model-agnostic** — works with any agent that supports MCP
- **Fully offline** — no external API calls required

---

## Architecture

```
┌─────────────────────────────────────────┐
│              AI Agent                   │
│  (Claude Code / Hermes / any MCP agent) │
└────────────────┬────────────────────────┘
                 │ MCP (stdio)
┌────────────────▼────────────────────────┐
│           MCP Server (server.py)        │
│                                         │
│  memory_store      memory_search        │
│  goal_add          goal_get_active      │
│  reflection_log    reflection_analyze   │
│  context_get_snapshot                   │
└────────────────┬────────────────────────┘
                 │ SQLite + ChromaDB
┌────────────────▼────────────────────────┐
│         Background Daemon (daemon.py)   │
│                                         │
│  • every 30 min → reflection analyzer  │
│  • every 60 min → goal monitor         │
│  • every  6 hrs → self maintenance     │
│  • every 24 hrs → memory decay         │
└─────────────────────────────────────────┘
```

---

## Installation

**Requirements:** Python 3.11+

```bash
git clone https://github.com/Roxmix/agentos-mcp.git
cd agentos-mcp

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
```

The first run will automatically download the embedding model (~90 MB).

---

## Running

Start both processes — each in its own terminal:

```bash
# Terminal 1 — MCP Server (talks to the agent)
python server.py

# Terminal 2 — Background Daemon (runs continuously)
python daemon.py
```

The daemon is optional but required for the "semi-alive" behavior (proactive insights, memory decay, goal alerts).

---

## Connecting to an Agent

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "agentos": {
      "command": "python",
      "args": ["/absolute/path/to/agentos/server.py"]
    }
  }
}
```

Restart Claude Desktop. A 🔨 icon will appear confirming the connection.

### Claude Code

```bash
claude mcp add-json agentos '{
  "command": "python",
  "args": ["/absolute/path/to/agentos/server.py"]
}'
```

Verify with `/mcp` inside Claude Code.

### Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  agentos:
    command: /path/to/agentos/.venv/bin/python3
    args:
    - /path/to/agentos/server.py
    cwd: /path/to/agentos
    env:
      SSL_CERT_FILE: /etc/ssl/certs/ca-certificates.crt
    enabled: true
```

---

## Available MCP Tools

### Memory
| Tool | Description |
|------|-------------|
| `memory_store` | Store a new memory with type and importance |
| `memory_search` | Semantic search across memories |
| `memory_list` | List recent memories |
| `memory_update_importance` | Update a memory's importance score |
| `memory_delete` | Delete a specific memory |

### Goals
| Tool | Description |
|------|-------------|
| `goal_add` | Add a new goal with priority, urgency, deadline |
| `goal_get_active` | Get active goals sorted by composite priority |
| `goal_update_progress` | Update progress on a goal |
| `goal_update_status` | Change goal status |
| `goal_list` | List goals by status |

### Reflection
| Tool | Description |
|------|-------------|
| `reflection_log` | Log an action and its outcome |
| `reflection_analyze` | Detect patterns from recent logs |
| `reflection_get_patterns` | Retrieve stored patterns |
| `reflection_get_summary` | Performance summary over N days |

### Context
| Tool | Description |
|------|-------------|
| `context_get_snapshot` | Unified cognitive state (memories + goals + insights + daemon status) |

### Approval
| Tool | Description |
|------|-------------|
| `approval_list` | List pending approvals |
| `approval_get_details` | Get full details of an approval item |
| `approval_decide` | Approve or reject a pending action |
| `approval_history` | View past decisions |

### Thought Graph
| Tool | Description |
|------|-------------|
| `graph_add_node` | Add a node to the thought graph |
| `graph_add_edge` | Add a directed edge between two nodes |
| `graph_find_nodes` | Search for nodes |
| `graph_delete_node` | Delete a node and all its edges |
| `graph_stats` | Graph statistics |
| `graph_find_related_problems` | What blocks/causes problems for a goal? |
| `graph_impact_analysis` | What will be affected if this node changes? |
| `graph_find_required_skills` | What skills are needed for a task? |
| `graph_find_path` | Shortest path between two nodes |
| `graph_get_neighbors` | Get direct neighbors of a node |
| `graph_extract_from_text` | Auto-extract nodes/edges from text |
| `graph_extract_relationship` | Ask LLM about relationship between concepts |

---

## Recommended Agent Workflow

```
1. Session starts  → call context_get_snapshot
                     (loads memories, goals, daemon insights)

2. During work     → call memory_store for important information
                     call reflection_log after each significant action

3. New objective   → call goal_add

4. Session ends    → call reflection_analyze to update patterns
```

---

## Configuration

All settings are in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./agentos.db` | SQLite database path |
| `CHROMA_PERSIST_DIR` | `./chroma_store` | ChromaDB persistence directory |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformers model |
| `MEMORY_DECAY_RATE` | `0.01` | Daily decay rate for unaccessed memories |
| `REFLECTION_LOOKBACK_DAYS` | `7` | Days analyzed in reflection jobs |
| `PATTERN_MIN_FREQUENCY` | `3` | Minimum occurrences to flag as a pattern |

---

## Project Structure

```
agentos-mcp/
├── server.py              # MCP server entry point
├── daemon.py              # Background daemon entry point
├── config.py              # Settings via pydantic-settings
├── database.py            # SQLite schema and async helpers
├── gateway.py             # FastAPI HTTP dashboard for approval queue
├── pyproject.toml         # Project metadata and dependencies
├── requirements.txt       # Python dependencies
│
├── modules/
│   ├── memory/            # Store, retrieve, importance scoring
│   ├── goals/             # CRUD, priority calculation
│   ├── reflection/        # Action logging, pattern detection
│   └── context/           # Unified snapshot builder
│
├── tools/                 # MCP tool definitions (one file per module)
│   ├── memory_tools.py
│   ├── goal_tools.py
│   ├── reflection_tools.py
│   ├── context_tools.py
│   ├── approval_tools.py
│   └── graph_tools.py
│
├── events/                # Inter-process event system
│   ├── bus.py, store.py, dispatcher.py, schema.py
│   └── handlers/          # memory, goal, reflection handlers
│
├── approval/              # Human-in-the-loop system
│   ├── queue.py, executor.py, webhook.py
│   └── actions/           # memory, goal, system actions
│
├── graph/                 # Thought graph
│   ├── schema.py, store.py, traversal.py, extractor.py
│
├── daemon/
│   ├── writer.py          # Shared DB writer for all jobs
│   └── jobs/              # 4 scheduled jobs
│
├── tests/                 # Test suite
│   └── test_agentos.py    # 9 smoke tests
│
└── .github/workflows/     # CI/CD
    └── ci.yml             # GitHub Actions
```

---

## Roadmap

- [ ] PostgreSQL support for multi-user deployments
- [ ] REST API alongside MCP
- [ ] Web dashboard for monitoring agent state
- [ ] Plugin system for custom observers and tools
- [ ] Multi-agent memory sharing

---

## License

MIT — see [LICENSE](LICENSE)
