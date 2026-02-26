# Agent Setup Instructions

This file is intended to be given to an AI agent to set up this MCP server on a new machine. Copy the prompt below and run it inside an agent session opened in this repository's directory.

---

## Prompt to give your AI agent

```
Read README.md and set up the my-own-mcp-server MCP server on this machine. Here is exactly what to do:

1. Verify Python 3.11+ is available. If not, stop and tell me.

2. Install all dependencies. Use uv if available (preferred), otherwise pip:
   uv sync
   # or: pip install "mcp[cli]>=1.0.0" "numpy>=1.24.0" "sentence-transformers>=3.0.0"
   On Debian/Ubuntu, if pip fails with "externally-managed-environment", add --break-system-packages:
   pip install --break-system-packages "mcp[cli]>=1.0.0" "numpy>=1.24.0" "sentence-transformers>=3.0.0"

3. Verify the server starts. Run it with a timeout so it exits automatically:
   If you used uv:  timeout 3 uv run python3 server.py 2>&1 || true
   If you used pip: timeout 3 python3 server.py 2>&1 || true
   Expected output: a line mentioning "Loaded: example_tool.py". If you see an ImportError or ModuleNotFoundError, the packages are not on the path — stop and report the error.
   Note: the first call to store_note or search_notes will download the all-MiniLM-L6-v2 model (~80MB from HuggingFace). This is normal and one-time only — if it appears to hang on first use, wait 30-60 seconds.

3b. If there are existing notes in data/db.sqlite that were created before semantic search was added, backfill their embeddings:
    If you used uv:  uv run python3 scripts/backfill_embeddings.py
    If you used pip: python3 scripts/backfill_embeddings.py
    (Safe to skip on a fresh install with no existing notes.)

4. Find the absolute path of the current directory (this repo) and the Python site-packages path:
   pwd
   python3 -c "import site; print(site.getsitepackages()[0])"
   If you used uv in step 2, use instead:
   uv run python3 -c "import site; print(site.getsitepackages()[0])"

5. Copy .mcp.json.example to .mcp.json and replace:
   - <absolute-path-to-repo> with the path from step 4
   - <python-site-packages-path> with the site-packages path from step 4

6. Ask me: do you want to register this server globally (available in all projects), or only for this project directory?

   - Project-only: .mcp.json is already in place, nothing more needed.
   - Globally: run this command (fill in the paths from step 4):
     claude mcp add --scope user my-own-mcp-server \
       --cwd <absolute-path-to-repo> \
       -e TRANSPORT=stdio \
       -e PYTHONPATH=<python-site-packages-path> \
       python3 <absolute-path-to-repo>/server.py

7. Ask me: do you want the skills available globally across all projects?

   - Yes: copy the skills to ~/.claude/skills/:
     mkdir -p ~/.claude/skills
     cp -r .claude/skills/learn-store-context ~/.claude/skills/
     cp -r .claude/skills/learn-load-context ~/.claude/skills/
     cp -r .claude/skills/learn-start-ui ~/.claude/skills/
   - No: the skills will only work inside this project directory.

8. Ask me: do you want to start the knowledge base UI? It requires Docker and shows all notes as an interactive graph.

   - Yes: run from the repo root:
     docker compose up -d --build ui
     Note: the first build takes 5-10 minutes (downloads torch and umap-learn). Subsequent builds are fast.
     Then open http://localhost:8000 in a browser. To stop: docker compose down.
   - No: skip this step.

9. Tell me to restart Claude Code. After restarting, confirm setup works by calling the `ping` tool — it should return `pong`.

Do not skip any step. If anything fails, stop and explain what went wrong.
```
