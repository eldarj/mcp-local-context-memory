# my-own-mcp-server

A private, locally-run [Model Context Protocol](https://modelcontextprotocol.io) server that gives Claude a persistent personal layer — custom tools, file storage, and a searchable knowledge base — all on your machine, nothing leaving it.

Claude Code spawns the server as a child process on startup (stdio transport). No Docker, no daemon, no open ports.

---

## What it changes

| Without this server | With this server |
|---|---|
| Re-explain project context every session | Load context with one tool call |
| Generated code lives only in chat history | Generated artefacts persist indefinitely |
| Claude forgets your preferences and decisions | Stored permanently, always retrievable |
| Search through old chat logs | Search notes by keyword instantly |
| Re-generate the same boilerplate repeatedly | Store once, retrieve and adapt anytime |
| Context window is the only memory | Effectively unlimited persistent memory |

---

## What it does

Once connected, Claude can:

- **Store and retrieve files/images** — save any content by name, get it back later
- **Maintain a knowledge base** — store notes, snippets, and context; search by keyword
- **Persist state across conversations** — everything lives in SQLite + local files and survives session restarts
- **Call custom tools** — drop a Python file in `tools/`, it's auto-loaded on next startup

A practical use of this: the `/learn-store-context` and `/learn-load-context` skills summarize conversations and store them as notes, so Claude can pick up where it left off across sessions.

---

## Quick Start

1. Install Python 3.11+ and ensure `pip` is available
2. Install the MCP SDK:
   ```bash
   pip install "mcp[cli]>=1.0.0"
   ```
3. Add to `~/.claude/mcp.json`:
   ```json
   {
     "mcpServers": {
       "my-own-mcp-server": {
         "command": "python3",
         "args": ["/absolute/path/to/my-own-mcp-server/server.py"],
         "cwd": "/absolute/path/to/my-own-mcp-server",
         "env": {
           "PYTHONPATH": "/path/to/site-packages"
         }
       }
     }
   }
   ```
4. Restart Claude Code — the server tools will appear automatically.

---

## Usage

### With Claude (normal mode)

Claude Code reads `.mcp.json` (or `~/.claude/mcp.json`) and spawns the server automatically when a session starts. You don't run anything manually — just talk to Claude:

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
| `search_notes(query)` | Full-text search across all notes |
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
├── server.py          # Entry point — init, tool registration, run
├── config.py          # Configuration (DATA_DIR)
├── db.py              # SQLite setup
├── modules/
│   ├── storage.py     # File storage tools
│   └── knowledge.py   # Knowledge base tools
├── tools/             # Drop custom tools here (auto-loaded)
├── data/              # Runtime data (gitignored)
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

---

## Data & Privacy

All data stays on your machine:
- Files stored in `data/files/`
- Notes and metadata in `data/db.sqlite`
- No network calls, no telemetry, no external services
- No open ports — the server communicates only through stdin/stdout with Claude Code
