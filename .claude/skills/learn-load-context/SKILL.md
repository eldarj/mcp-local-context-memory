---
name: learn-load-context
description: Load previously stored conversation context from the MCP server to restore memory of past sessions.
---

Load previously stored conversation context from the MCP server to restore memory of past sessions.

Steps:
1. Call the `list_notes` MCP tool with `tag="conversation"` to retrieve all stored conversation summaries.
2. If no notes are found, inform the user that no prior context exists yet and suggest running `/learn-store-context` at the end of a session.
3. If notes are found:
   - Present a brief overview of what sessions exist (keys and dates)
   - Load the most recent one using `get_note` and read it in full
   - If there are multiple recent entries (e.g. from the same project or last few days), load those too
4. Summarize what you've loaded back to the user: what project(s), what was discussed, what was left open.
5. Confirm you now have the context and are ready to continue from where things left off.
