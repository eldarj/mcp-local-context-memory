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

---

## Project Structure

```
my-own-mcp-server/
├── server.py              # Entry point — init, tool registration, run
├── config.py              # Config (DATA_DIR env var)
├── db.py                  # SQLite connection factory + schema init
├── modules/
│   ├── storage.py         # store_file / get_file / list_files / delete_file
│   └── knowledge.py       # store_note / get_note / search_notes / list_notes / delete_note
├── tools/                 # Drop custom tools here — auto-loaded on startup
│   └── example_tool.py   # Shows the register(mcp) pattern
├── data/                  # Runtime data — gitignored, created by db.init()
│   ├── db.sqlite
│   └── files/
├── .mcp.json              # Project-level MCP client config (stdio)
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
- Two tables: `notes` (key/body/tags/timestamps) and `files` (name/mime_type/tags/size/timestamp)

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

- **SQLite FTS5 full-text search** — current `search_notes` is LIKE-based; FTS5 gives proper tokenised search with relevance ranking
- **Note versioning** — keep edit history, allow diffing previous versions
- **File content search** — search text content of stored `.txt`, `.md`, `.py`, `.json` files
- **MCP Resources support** — expose notes/files as MCP Resources so Claude can read them directly into context without a tool call
- **Export / import** — `export_all` / `import_all` for backup and migration
- **Tagging improvements** — `list_tags`, `rename_tag`, `merge_tags` tools
- **Pagination** — `limit` and `offset` on `list_files` and `list_notes`
- **`rename_file` / `rename_note`** — move without delete-and-recreate
- **Bulk delete** — `delete_notes_by_tag`, `delete_files_by_tag`
- **Storage stats** — total counts, sizes, breakdown by tag

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

`.claude/settings.local.json` allows the following without prompting:
- `python3` — Python execution
- `git add`, `git commit` — version control
- `curl`, `chmod`, `ss` — utilities
- `mcp__my-own-mcp-server__*` — MCP tool calls
