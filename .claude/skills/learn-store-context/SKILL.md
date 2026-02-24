---
name: learn-store-context
description: Summarize the current conversation and store it as a note in the MCP server for future context retrieval.
---

Summarize our current conversation and store it as a note in the MCP server for future context retrieval.

Steps:
1. Review the full conversation so far and produce a concise summary covering:
   - The project(s) or topic(s) we discussed
   - Key decisions made or conclusions reached
   - Any code changes, files created, or tasks completed
   - Open threads or things left to do
2. Generate a key in the format `conversation/YYYY-MM-DD-HHMMSS` using today's date and current time. Today's date is available in the system context.
3. Call the `store_note` MCP tool with:
   - `key`: the generated key
   - `body`: the summary text
   - `tags`: `["conversation", "context"]` plus any relevant topic tags (e.g. `"mcp"`, `"setup"`, etc.)
4. Confirm to the user that the context was stored, including the key used.
