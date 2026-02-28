---
name: learn-start-ui
description: Start the visual knowledge base UI — a D3 force graph of all notes with clickable sidebar.
---

Start the knowledge base UI.

Prefer running locally with uvicorn (no Docker required).

## Local (recommended)

1. Install dependencies (one-time): `pip install -r ui/requirements.txt`
2. From the project root, run: `uvicorn ui.main:app --host 127.0.0.1 --port 8000 --reload`
3. Tell the user the UI is available at http://localhost:8000
4. The app auto-detects `data/db.sqlite` relative to the project root.
5. Static files are served from `ui/static/` — CSS/JS changes reflect immediately with `--reload`.
6. To stop: Ctrl+C

## Docker (alternative)

1. Run `docker compose up -d --build ui` from the project root.
2. Tell the user the UI is available at http://localhost:8000
3. To stop: `docker compose down`
