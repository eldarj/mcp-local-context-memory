---
name: learn-start-ui
description: Start the visual knowledge base UI — a UMAP scatter plot of all notes with clickable sidebar.
---

Start the knowledge base UI.

Steps:
1. Run `docker compose up -d --build ui` from the project root (`/home/ejahijagic/projects/playground-my-own-mcp-server`).
2. Wait for the command to complete. First build takes a few minutes (installing umap-learn + torch deps); subsequent runs are fast.
3. Tell the user the UI is available at http://localhost:8000
4. Note: the UMAP layout computes on page load — expect 5–15 seconds before nodes appear, depending on note count.
5. To stop: `docker compose down`
