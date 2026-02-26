# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Purpose

`my-own-mcp-server` is a private, locally-run MCP server that gives Claude a persistent personal layer across all sessions and projects. Claude Code spawns it as a child process on startup (stdio transport) — no Docker, no daemon, no open ports.

It provides:
- **File storage** — store and retrieve files/images by name
- **Knowledge base** — store, search, and retrieve notes/snippets
- **Custom tools** — drop a `.py` file in `tools/`, it's auto-loaded on next startup
- **Cross-session memory** — data lives in SQLite and survives session restarts

The `/learn-store-context` and `/learn-load-context` skills are built on top of this: they summarize conversations into notes so Claude can resume with context in future sessions. The skills ship with this repo in `.claude/skills/` (available to anyone who clones or forks it) and can optionally be copied to `~/.claude/skills/` to make them available globally across all your projects.

---

## Technology Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| MCP SDK | `mcp[cli]` (Anthropic official) |
| Transport | stdio — Claude Code spawns the process directly |
| Storage | SQLite (`data/db.sqlite`) + filesystem (`data/files/`) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) + `numpy` |
| UI | FastAPI + D3.js (Dockerised, separate from MCP server) |

---

## Project Structure

```
my-own-mcp-server/
├── server.py              # Entry point — init, tool registration, run
├── config.py              # Config (DATA_DIR env var)
├── db.py                  # SQLite connection factory + schema init
├── modules/
│   ├── storage.py         # store_file / get_file / list_files / delete_file
│   ├── knowledge.py       # store_note / get_note / search_notes / list_notes / delete_note
│   └── embeddings.py      # Lazy-loads all-MiniLM-L6-v2; encode / to_blob / from_blob / rank
├── scripts/
│   └── backfill_embeddings.py  # One-time migration to generate embeddings for existing notes
├── tools/                 # Drop custom tools here — auto-loaded on startup
│   └── example_tool.py    # Shows the register(mcp) pattern
├── ui/                    # Dockerised knowledge base UI (separate from MCP server)
│   ├── Dockerfile
│   ├── main.py            # FastAPI: /api/graph (cosine similarity links) + /api/notes/:key
│   ├── requirements.txt
│   └── static/            # D3 force graph, light theme, markdown sidebar
├── docker-compose.yml     # UI service only — MCP server runs via stdio, not Docker
├── .claude/
│   └── skills/
│       ├── learn-store-context/   # Skill: summarize and store session context
│       ├── learn-load-context/    # Skill: restore context from a previous session
│       └── learn-start-ui/        # Skill: start the knowledge base UI
├── .mcp.json.example      # Copy to .mcp.json and fill in your paths (gitignored)
├── AGENT_SETUP.md         # Prompt for AI-assisted setup
├── data/                  # Runtime data — gitignored, created by db.init()
│   ├── db.sqlite
│   └── files/
└── pyproject.toml
```

To make the server available in all projects, register it at user scope via `claude mcp add --scope user` (see MCP Client Config section below). This writes into `~/.claude.json`, which Claude Code reads globally.

---

## Architecture

### Startup sequence (`server.py`)
1. `db.init()` — creates `data/` dirs and SQLite tables (idempotent)
2. `FastMCP(SERVER_NAME)` — creates the MCP server instance
3. Built-in `ping` tool registered directly on `mcp`
4. `storage.register(mcp)` and `knowledge.register(mcp)` — module tools registered
5. Dynamic loader — scans `tools/*.py`, calls `register(mcp)` on each
6. `mcp.run(transport="stdio")` — blocks; Claude Code owns the process lifecycle

### Database (`db.py`)
- `db.init()` is idempotent — safe to call every startup
- `db.connect()` is a context manager: commits on success, rolls back on exception, always closes
- Three tables: `notes` (key/body/tags/timestamps), `files` (name/mime_type/tags/size/timestamp), `note_embeddings` (key, embedding BLOB)

### Semantic search (`modules/embeddings.py`)
- Lazy-loads `all-MiniLM-L6-v2` on first call (22M params, ~80MB, CPU-only)
- `store_note` automatically generates and stores an embedding alongside the note body
- `search_notes` defaults to semantic search (cosine similarity via `rank()`); pass `keyword=True` for LIKE fallback
- Embeddings stored as `float32` BLOBs in `note_embeddings`; `to_blob` / `from_blob` handle serialisation

### Knowledge base UI (`ui/`)
- Separate Dockerised FastAPI app — reads `data/db.sqlite` directly via read-only volume mount
- `/api/graph`: loads all note embeddings, computes pairwise cosine similarities, returns top-3 neighbour links per note
- `/api/notes/:key`: returns full note body + metadata
- Frontend: D3 force simulation where link strength ∝ similarity; nodes sized by body length, coloured by specific tag
- Start with `/learn-start-ui` or `docker compose up -d --build ui`
- Static files (`ui/static/`) are volume-mounted — CSS/JS changes reflect on refresh without rebuilding

### Adding a dynamic tool
Drop a `.py` file into `tools/`. It must export `register(mcp)`:
```python
def register(mcp):
    @mcp.tool()
    def my_tool(arg: str) -> str:
        """Description Claude will see."""
        return f"result: {arg}"
```
Restart Claude Code for the tool to be picked up. Files starting with `_` are skipped (use this to temporarily disable a tool without deleting it).

Multiple tools can be registered from one file:
```python
def register(mcp):
    @mcp.tool()
    def add(a: float, b: float) -> str:
        """Add two numbers."""
        return str(a + b)

    @mcp.tool()
    def multiply(a: float, b: float) -> str:
        """Multiply two numbers."""
        return str(a * b)
```

Tool that reads from the database — `db` is importable from the project root:
```python
import db

def register(mcp):
    @mcp.tool()
    def note_count() -> str:
        """Return the total number of stored notes."""
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        return f"{count} notes stored."
```

Tool that calls an external process:
```python
import subprocess

def register(mcp):
    @mcp.tool()
    def git_log(n: int = 5) -> str:
        """Return the last n git commit messages from the current repo."""
        result = subprocess.run(
            ["git", "log", f"-{n}", "--oneline"],
            capture_output=True, text=True,
        )
        return result.stdout or result.stderr
```

---

## Future Improvements

Roughly ordered by impact:

- **Note versioning** — keep edit history, allow diffing previous versions
- **File content search** — extend semantic search to stored `.txt`, `.md`, `.py`, `.json` files
- **MCP Resources support** — expose notes/files as MCP Resources so Claude can read them directly into context without a tool call
- **Export / import** — `export_all` / `import_all` for backup and migration
- **SQLite FTS5** — replace LIKE-based keyword fallback with proper tokenised full-text search
- **Tagging improvements** — `list_tags`, `rename_tag`, `merge_tags` tools
- **Pagination** — `limit` and `offset` on `list_files` and `list_notes`
- **`rename_file` / `rename_note`** — move without delete-and-recreate
- **Bulk delete** — `delete_notes_by_tag`, `delete_files_by_tag`
- **Storage stats** — total counts, sizes, breakdown by tag
- **UI: search bar** — filter visible nodes by semantic query
- **UI: cache graph layout** — persist computed positions so large graphs don't recompute on every load

---

## Commands

### Inspect stored data
```bash
sqlite3 data/db.sqlite ".tables"
sqlite3 data/db.sqlite "SELECT key, tags FROM notes;"
sqlite3 data/db.sqlite "SELECT name, mime_type, size_bytes FROM files;"
ls data/files/
```

---

## MCP Client Config

`.mcp.json` at the project root is pre-configured. Claude Code picks it up automatically when you open this directory.

To make the server available globally across all projects, add it at user scope:

```bash
claude mcp add --scope user my-own-mcp-server \
  -e TRANSPORT=stdio \
  -e PYTHONPATH=/home/you/.local/lib/python3.12/site-packages \
  --cwd /path/to/playground-my-own-mcp-server \
  python3 /path/to/playground-my-own-mcp-server/server.py
```

This writes the config into `~/.claude.json`. Note: `~/.claude/mcp.json` is **not** read by Claude Code — the correct global config location is `~/.claude.json`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `./data` | Root for SQLite db and file storage |

---

## Pre-Configured Permissions

`.claude/settings.local.json` is gitignored (it contains machine-specific paths). Create it locally to pre-approve common operations without prompting:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "mcp__my-own-mcp-server__*"
    ]
  }
}
```
