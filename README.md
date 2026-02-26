# my-own-mcp-server

A private, locally-run [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude a persistent personal layer — custom tools, file storage, and a searchable knowledge base — all on your machine, nothing leaving it.

Claude Code spawns the server as a child process on startup (stdio transport). No Docker, no daemon, no open ports.

> **Using Cursor?** The MCP server works with any MCP-compatible client. See [CURSOR_SETUP.md](CURSOR_SETUP.md) for Cursor-specific setup instructions — open it in a Cursor Agent session and it will configure everything for you.

---

## What it does

| Without this server | With this server |
|---|---|
| Re-explain project context every session | Load context with one tool call |
| Generated code lives only in chat history | Generated artefacts persist indefinitely |
| Claude forgets your preferences and decisions | Stored permanently, always retrievable |
| Search through old chat logs | Search notes by keyword instantly |
| Re-generate the same boilerplate repeatedly | Store once, retrieve and adapt anytime |
| Context window is the only memory | Effectively unlimited persistent memory |

Once connected, Claude can:

- **Store and retrieve files/images** — save any content by name, get it back later
- **Maintain a knowledge base** — store notes, snippets, and context; search by meaning (semantic) or keyword
- **Persist state across conversations** — everything lives in SQLite + local files and survives session restarts
- **Call custom tools** — drop a Python file in `tools/`, it's auto-loaded on next startup
- **Visualise the knowledge base** — a local web UI shows all notes as an interactive graph, clustered by semantic similarity

---

## Upgrading from a previous version

If you already have this server running and are pulling new changes, do this before restarting:

**1. Install new dependencies** (the server will fail to start without these):
```bash
uv sync
# or: pip install --break-system-packages "numpy>=1.24.0" "sentence-transformers>=3.0.0"
```

**2. Backfill embeddings for existing notes** (semantic search returns nothing without this):
```bash
# uv:
uv run python3 scripts/backfill_embeddings.py
# pip:
python3 scripts/backfill_embeddings.py
```

**3. Note: `search_notes` now defaults to semantic search**
The `query` parameter is now matched by meaning, not exact keywords. To preserve old keyword behaviour, pass `keyword=True`:
```
search_notes(query="authentication", keyword=True)
```

---

## Quick Start

> **Prefer to let your AI do it?** Open this repo in Claude Code and paste the prompt from [AGENT_SETUP.md](AGENT_SETUP.md) — it will run through the entire setup for you. Otherwise, follow the steps below manually.

1. Install Python 3.11+
2. Install the MCP SDK. Pick one approach and stick with it — the choice affects your `PYTHONPATH` in step 3:

   **Option A — uv (recommended, uses `pyproject.toml`):**
   ```bash
   uv sync
   ```
   Your site-packages path will be inside `.venv/`:
   ```bash
   .venv/lib/python3.x/site-packages   # replace 3.x with your Python version
   ```
   Or get it precisely with:
   ```bash
   uv run python3 -c "import site; print(site.getsitepackages()[0])"
   ```

   **Option B — pip (global install):**
   ```bash
   pip install "mcp[cli]>=1.0.0"
   ```
   Get your site-packages path with:
   ```bash
   python3 -c "import site; print(site.getsitepackages()[0])"
   ```

3. Copy `.mcp.json.example` to `.mcp.json` and fill in your paths:
   ```bash
   cp .mcp.json.example .mcp.json
   ```
   Edit `.mcp.json` — replace `<absolute-path-to-repo>` with the absolute path to this directory, and `<python-site-packages-path>` with the site-packages path from step 2.
4. Restart Claude Code — the server tools will appear automatically.
5. *(Optional)* Enable the `/learn-store-context` and `/learn-load-context` skills globally:
   ```bash
   mkdir -p ~/.claude/skills
   cp -r .claude/skills/learn-store-context ~/.claude/skills/
   cp -r .claude/skills/learn-load-context ~/.claude/skills/
   ```
   These skills let Claude summarize and restore session context across conversations. Without this step the skills still work inside this project directory, but won't be available in other projects.

To make the server available globally across all projects, register it at user scope:

```bash
claude mcp add --scope user my-own-mcp-server \
  --cwd /absolute/path/to/repo \
  -e TRANSPORT=stdio \
  -e PYTHONPATH=$(python3 -c "import site; print(site.getsitepackages()[0])") \
  python3 /absolute/path/to/repo/server.py
```

This writes into `~/.claude.json`, which Claude Code reads globally. Note: `~/.claude/mcp.json` is **not** read by Claude Code.

---

## Usage

### Commands

Two skills ship with this repo for cross-session memory. Type either directly into any Claude Code conversation:

| Command | What it does |
|---|---|
| `/learn-store-context` | Summarizes the current conversation and saves it as a note — run this at the end of a session |
| `/learn-load-context` | Loads and reads back previously stored summaries — run this at the start of a new session to pick up where you left off |
| `/learn-start-ui` | Starts the knowledge base UI at http://localhost:8000 (requires Docker) |

These work inside this project directory out of the box. To use them in any project, copy them to `~/.claude/skills/` (see Quick Start step 5).

---

### With Claude (normal mode)

Claude Code reads `.mcp.json` (or the global `~/.claude.json`) and spawns the server automatically when a session starts. You don't run anything manually — just talk to Claude:

> "Store a note with key 'project/decisions', body 'Chose Postgres over MySQL for JSONB support.', tags ['project', 'decisions']."

> "Search my notes for anything about authentication."

> "Get the note 'project/decisions'."

> "List all files tagged 'screenshot'."

> "Save this JSON as 'configs/app.json' on my-own-mcp-server." *(Claude handles base64 encoding automatically.)*

The server process lives and dies with your Claude Code session. Your data in `data/` persists between sessions.

### Manually (inspect and debug)

The server binary can be run directly for testing — it speaks the MCP stdio protocol, so it will block waiting for input. Use `Ctrl+C` to exit:

```bash
python3 server.py
# stderr: [tools] Loaded: example_tool.py
# (blocks on stdin — Ctrl+C to exit)
```

To inspect stored data directly without going through Claude:

```bash
# List all notes
sqlite3 data/db.sqlite "SELECT key, tags, updated_at FROM notes ORDER BY updated_at DESC;"

# Read a specific note
sqlite3 data/db.sqlite "SELECT body FROM notes WHERE key = 'project/decisions';"

# List all files with sizes
sqlite3 data/db.sqlite "SELECT name, mime_type, size_bytes FROM files;"

# Browse raw files on disk
ls -lh data/files/
```

---

## Available Tools

These are the underlying MCP tools the server exposes. In normal use you won't call them directly — the skills (`/learn-store-context`, `/learn-load-context`) and Claude itself call them automatically in the background. You can invoke them explicitly if you want to debug or do something one-off (e.g. "list all my notes tagged 'project-x'").

### System
| Tool | Description |
|---|---|
| `ping` | Health check — confirms the server is reachable |

### File Storage
| Tool | Description |
|---|---|
| `store_file(name, content_base64, mime_type, tags[])` | Save a file, image, or document |
| `get_file(name)` | Retrieve file content by name |
| `list_files(tag?)` | List all stored files (optionally filter by tag) |
| `delete_file(name)` | Remove a stored file |

### Knowledge Base
| Tool | Description |
|---|---|
| `store_note(key, body, tags[])` | Save a text note or snippet |
| `get_note(key)` | Retrieve a note by key |
| `search_notes(query, keyword?)` | Semantic search by default; pass `keyword=True` for exact LIKE-based search |
| `list_notes(tag?)` | List all notes (optionally filter by tag) |
| `delete_note(key)` | Remove a note |

---

## Adding Your Own Tools

Drop a `.py` file into `tools/`:

```python
# tools/my_tool.py

def register(mcp):
    @mcp.tool()
    def greet(name: str) -> str:
        """Greet someone by name."""
        return f"Hello, {name}!"
```

Restart Claude Code. The tool is now available. See `CLAUDE.md` for more tool patterns.

---

## Organising with Tags

Both notes and files support a `tags` list. Suggested conventions:

| Pattern | Example |
|---|---|
| By project | `project-name` |
| By type | `snippet`, `config`, `screenshot`, `reference` |
| By language | `python`, `sql`, `bash` |
| By status | `wip`, `done`, `archived` |

---

## Project Structure

```
my-own-mcp-server/
├── server.py              # Entry point — init, tool registration, run
├── config.py              # Configuration (DATA_DIR)
├── db.py                  # SQLite setup
├── modules/
│   ├── storage.py         # File storage tools
│   ├── knowledge.py       # Knowledge base tools (semantic search)
│   └── embeddings.py      # sentence-transformers encoder + SQLite blob helpers
├── scripts/
│   └── backfill_embeddings.py  # One-time migration for existing notes
├── tools/                 # Drop custom tools here (auto-loaded)
├── ui/                    # Knowledge base web UI
│   ├── Dockerfile
│   ├── main.py            # FastAPI: /api/graph + /api/notes/:key
│   ├── requirements.txt
│   └── static/            # index.html, app.js, style.css (D3 force graph)
├── docker-compose.yml     # UI service only (MCP server is not in Docker)
├── .claude/
│   └── skills/
│       ├── learn-store-context/   # Skill: summarize and store session context
│       ├── learn-load-context/    # Skill: restore context from a previous session
│       └── learn-start-ui/        # Skill: start the knowledge base UI
├── .mcp.json.example      # Copy to .mcp.json and fill in your paths
├── AGENT_SETUP.md         # Prompt for AI-assisted setup
├── data/                  # Runtime data (gitignored)
│   ├── db.sqlite
│   └── files/
└── pyproject.toml
```

---

## Storage Details

| Aspect | Detail |
|---|---|
| File location | `data/files/<name>` — preserves path structure |
| Database | `data/db.sqlite` |
| Max file size | No enforced limit — constrained by disk space |
| Note body size | No enforced limit — SQLite TEXT is unbounded |
| Tag format | JSON array stored as TEXT: `["tag1","tag2"]` |
| Upsert behaviour | `store_file` and `store_note` overwrite on key conflict |

---

## Intentional Limitations

- No authentication — local only, single owner
- No encryption at rest — plain SQLite + files
- No automatic backup — manage `data/` yourself
- No note/file versioning — overwrite is destructive
- No network exposure — communicates only via stdin/stdout with Claude Code

---

## Backup

```bash
cp data/db.sqlite data/db.sqlite.bak
cp -r data/files data/files.bak
```

To move to another machine: copy the entire `data/` directory.

---

## Verification

After setup, confirm everything works:

```bash
# 1. Verify the server starts
python3 server.py
# Expected stderr: "[tools] Loaded: example_tool.py" then blocks on stdin. Ctrl+C to exit.

# 2. Verify db and files dirs were created
ls data/
# Expected: db.sqlite  files/

sqlite3 data/db.sqlite ".tables"
# Expected: files  notes
```

Then in a Claude conversation:
- `ping` → should return `pong`
- `store_note` with a test key → retrieve it back → confirm it persists after restarting Claude Code

---

## Requirements

- Python 3.11+
- `mcp[cli]>=1.0.0`
- `numpy>=1.24.0`
- `sentence-transformers>=3.0.0`
- Docker (optional — only needed for the UI)

---

## Data & Privacy

All data stays on your machine:
- Files stored in `data/files/`
- Notes and metadata in `data/db.sqlite`
- No network calls, no telemetry, no external services
- No open ports — the server communicates only through stdin/stdout with Claude Code

---

## Future Todos

- **SQLite FTS5** — replace LIKE-based keyword fallback with proper tokenised full-text search
- **Note versioning** — keep edit history before overwriting
- **Export / import** — `export_all` / `import_all` for backup and migration
- **UI: cache UMAP/graph layout** — avoid recomputing on every page load at large scale
- **UI: search bar** — filter visible nodes by query
