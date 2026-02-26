# Cursor Agent Setup Instructions

This file is intended to be read and executed by a Cursor Agent. It covers everything needed to connect this MCP server to Cursor so that its tools are available to any model running inside Cursor (Claude, Gemini, GPT, or any other).

---

## What this repo is

`my-own-mcp-server` is a locally-run [Model Context Protocol](https://modelcontextprotocol.io) server. Once connected to Cursor, it gives the agent persistent storage across sessions:

- **store_note / get_note / search_notes / list_notes / delete_note** — a searchable knowledge base
- **store_file / get_file / list_files / delete_file** — file and image storage
- **ping** — health check

All data lives in a local SQLite database (`data/db.sqlite`) and `data/files/` on disk. Nothing leaves the machine.

---

## Step 1 — Install dependencies

Check Python 3.11+ is available:

```bash
python3 --version
```

Install the MCP SDK. Use uv if available (preferred, `pyproject.toml` is already configured), otherwise pip:

```bash
uv sync
# or: pip install "mcp[cli]>=1.0.0"
```

Determine the site-packages path — you will need this in Step 2:

```bash
# If you used uv:
uv run python3 -c "import site; print(site.getsitepackages()[0])"

# If you used pip:
python3 -c "import site; print(site.getsitepackages()[0])"
```

Verify the server starts:

```bash
timeout 3 python3 server.py 2>&1 || true
```

Expected output contains a line like `[tools] Loaded: example_tool.py`. If you see an `ImportError` or `ModuleNotFoundError`, the MCP SDK is not on the path — stop and report the error.

---

## Step 2 — Configure Cursor MCP

The MCP server config for Cursor uses the same JSON format in both project-level and global scope.

Determine the absolute path to this repo:

```bash
pwd
```

### Option A — Project-level (this repo only)

Create `.cursor/mcp.json` in the root of this repository:

```json
{
  "mcpServers": {
    "my-own-mcp-server": {
      "command": "python3",
      "args": ["<absolute-path-to-repo>/server.py"],
      "cwd": "<absolute-path-to-repo>",
      "env": {
        "TRANSPORT": "stdio",
        "PYTHONPATH": "<python-site-packages-path>"
      }
    }
  }
}
```

Replace `<absolute-path-to-repo>` with the path from `pwd` and `<python-site-packages-path>` with the path from Step 1.

### Option B — Global (available in all Cursor projects)

**Via settings file** — create or edit `~/.cursor/mcp.json` with the same JSON block as above.

**Via Cursor UI** — open Cursor Settings → Features → MCP → Add new MCP server, and fill in:
- Name: `my-own-mcp-server`
- Command: `python3 <absolute-path-to-repo>/server.py`
- Working directory: `<absolute-path-to-repo>`
- Environment variables: `TRANSPORT=stdio`, `PYTHONPATH=<python-site-packages-path>`

---

## Step 3 — Restart Cursor

After writing the config, tell the user to restart Cursor. Once restarted, verify the server is connected by calling the `ping` tool — it should return `pong`.

---

## Step 4 — Ask the user about scope preference

Ask the user: did you set this up project-level or globally?

- **Project-level**: the tools are available only when Cursor is opened in this directory.
- **Global**: the tools are available in every Cursor project.

---

## How to use the tools (no skills in Cursor)

Cursor does not have a `/skills` system, so there are no `/learn-store-context` or `/learn-load-context` slash commands. Instead, call the underlying MCP tools directly:

**To save context at the end of a session** — call `store_note` with:
- `key`: `conversation/YYYY-MM-DD-HHMMSS` (use the current date and time)
- `body`: a concise summary covering what was discussed, decisions made, code changed, and open threads
- `tags`: a **comma-separated string**, e.g. `"conversation,context"` (do not pass an array; Cursor’s MCP layer can produce invalid JSON when tool arguments are arrays)

**To restore context at the start of a new session** — call `list_notes` with `tag="conversation"` to see all stored summaries, then call `get_note` on the most recent one (or a few if relevant).

You can also use the tools for anything else:
- Store snippets, configs, or reference material with `store_note`
- Save files or images with `store_file`
- Search across everything with `search_notes`

---

## Reference — all available tools

| Tool | Description |
|---|---|
| `ping` | Health check |
| `store_note(key, body, tags?)` | Save a text note or snippet. tags optional, comma-separated string. |
| `get_note(key)` | Retrieve a note by key |
| `search_notes(query)` | Keyword search across all notes |
| `list_notes(tag?)` | List all notes, optionally filtered by tag |
| `delete_note(key)` | Delete a note |
| `store_file(name, content_base64, mime_type, tags?)` | Save a file or image. tags optional, comma-separated string. |
| `get_file(name)` | Retrieve a file by name |
| `list_files(tag?)` | List all stored files, optionally filtered by tag |
| `delete_file(name)` | Delete a file |
