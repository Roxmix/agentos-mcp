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

## Quick Setup

**Requirements:** Python 3.11+

### Option 1: Install from PyPI (recommended)

```bash
pip install agentos-mcp
```

That's it. Then create your `.env` and start both processes:

```bash
cp .env.example .env   # if running from source
agentos-server         # Terminal 1 — MCP server
agentos-daemon         # Terminal 2 — background daemon (optional)
```

### Option 2: Install from source

```bash
git clone https://github.com/Roxmix/agentos-mcp.git
cd agentos-mcp

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e .

cp .env.example .env
```

The first run will automatically download the embedding model (~90 MB).

---

## Running

Start both processes — each in its own terminal:

```bash
# Terminal 1 — MCP Server (talks to the agent)
agentos-server
# or: python server.py

# Terminal 2 — Background Daemon (runs continuously)
agentos-daemon
# or: python daemon.py
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
      "command": "agentos-server"
    }
  }
}
```

Restart Claude Desktop. A 🔨 icon will appear confirming the connection.

### Claude Code

```bash
claude mcp add-json agentos '{
  "command": "agentos-server"
}'

Verify with `/mcp` inside Claude Code.

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
| `AGENTOS_DB_PATH` | `~/.agentos/agentos.db` | SQLite database path (set to use a custom location) |
| `CHROMA_PERSIST_DIR` | `./chroma_store` | ChromaDB persistence directory |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformers model |
| `MEMORY_DECAY_RATE` | `0.01` | Daily decay rate for unaccessed memories |
| `REFLECTION_LOOKBACK_DAYS` | `7` | Days analyzed in reflection jobs |
| `PATTERN_MIN_FREQUENCY` | `3` | Minimum occurrences to flag as a pattern |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

**Note:** The database is stored at `~/.agentos/agentos.db` by default. This ensures the MCP server and daemon share the same database whether installed via pip or run from source. Set `AGENTOS_DB_PATH` to use a custom location.

---

## Project Structure

```
agentos-mcp/
├── server.py              # MCP server entry point
├── daemon.py              # Background daemon entry point
├── config.py              # Settings via pydantic-settings
├── database.py            # SQLite schema and async helpers
│
├── modules/
│   ├── memory/            # Store, retrieve, importance scoring
│   ├── goals/             # CRUD, priority calculation
│   ├── reflection/        # Action logging, pattern detection
│   └── context/           # Unified snapshot builder
│
├── tools/                 # MCP tool definitions (one file per module)
│
├── daemon_pkg/            # Background daemon package
│   ├── writer.py          # Shared DB writer for all jobs
│   └── jobs/
│       ├── memory_decay_job.py
│       ├── goal_monitor_job.py
│       ├── reflection_analyzer_job.py
│       └── self_maintenance_job.py
│
├── tests/                 # Test suite
├── pyproject.toml         # Package metadata & dependencies
├── .env.example           # Configuration template
└── .github/workflows/     # CI/CD (GitHub Actions)
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
