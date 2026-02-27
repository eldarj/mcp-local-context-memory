---
name: learn-summarize-repo
description: Walk the current repo, read key files, and store a structured summary note for future reference.
---

Summarize the repository you are currently working in and store the result as a persistent note.

Steps:
1. Identify the current repo:
   - Run `git rev-parse --show-toplevel` to get the repo root path.
   - Extract the repo name from the last path segment (e.g. `my-service`).

2. Collect key files to read (in this order, skip if not present):
   - `README.md` or `README.rst`
   - Top-level config: `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`
   - Entry points: `main.py`, `index.ts`, `index.js`, `app.py`, `server.py`, `cmd/main.go`
   - `CLAUDE.md` (project instructions, if present)
   - Directory listing of the top level (1 level deep) to understand the module/package layout
   - Up to 3 major source modules or directories — read their `__init__.py`, `index.ts`, or equivalent entrypoint if present

3. Produce a structured summary using exactly these sections:

   ## Tech Stack
   Table with columns: Language | Framework | Key Libraries | Runtime / Build Tool

   ## Architecture
   2–4 sentences on how the system is structured: layers, services, or modules and how they interact.

   ## Entry Points
   Bulleted list: `filename` — what it does

   ## Key Files & Modules
   Bulleted list: `path` — purpose

   ## Configuration & Environment
   List any env vars, config files, and what they control. If none found, state "None identified."

   ## Notable Patterns
   Bullet points: architectural decisions, design patterns, or conventions visible in the code.

   ## Open Questions
   Any ambiguities, undocumented areas, or things that need clarification from the team. If none, write "None."

4. Call `store_note` with:
   - `key`: `repo-summary/<repo-name>`
   - `body`: the structured summary from step 3
   - `tags`: `repo-summary,<repo-name>,architecture` plus any language/framework tags (e.g. `python`, `fastapi`, `typescript`, `go`)

5. Confirm to the user: "Stored repo summary as `repo-summary/<repo-name>`."
