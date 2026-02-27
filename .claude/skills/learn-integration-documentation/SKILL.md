---
name: learn-integration-documentation
description: Document the integration surface of the current repo (REST endpoints, events, SDKs, env vars) and store it as a note.
---

Document what this service exposes for external callers and store it as a persistent integration reference.

## Default Acceptance Criteria

Apply these criteria to every piece of integration surface you document. Do not skip or approximate any of them:

- Every HTTP endpoint must include: method, path, all request parameters (query, path, header), request body schema (field names + types + required/optional), response schema, and all relevant HTTP status codes.
- Every event or message schema must include: name, direction (produced/consumed), all fields (name + type + required/optional), and the transport/topic/queue it travels on.
- Every environment variable that external callers must supply must be listed with: name, type, default value if any, and a description of its purpose.
- All authentication and authorization mechanisms must be documented in full (API keys, OAuth scopes, JWT claims, mTLS, etc.).
- Any versioning strategy must be noted (URL prefix like `/v1/`, `Accept` header, custom header, etc.).
- Any field, endpoint, or behaviour that is ambiguous or not explicitly documented in the source code must be flagged with `[UNDOCUMENTED — verify]` rather than guessed or omitted.

## Steps

1. Identify the current repo:
   - Run `git rev-parse --show-toplevel` to get the repo root.
   - Extract the repo name.

2. Locate integration surfaces by searching the codebase:
   - **REST endpoints**: route decorators (`@app.route`, `@router.get`, `app.get`, `@Controller`, `router.HandleFunc`, etc.)
   - **Event / message schemas**: event class definitions, payload types, Protobuf/Avro/JSON Schema files
   - **Webhooks**: outbound webhook registrations or inbound webhook handler routes
   - **SDK interfaces**: exported classes or functions in public package entrypoints (`index.ts`, `__init__.py`, etc.)
   - **Exported types**: TypeScript interfaces, Python TypedDicts, Pydantic models used at API boundaries
   - **Caller-supplied env vars**: `os.getenv`, `process.env`, config schema classes

3. Document each surface with full detail, applying all acceptance criteria above. Structure the note as follows:

   ## Overview
   One paragraph: what does this service do, and what can external integrators do with it?

   ## HTTP API

   For each endpoint:
   ### `METHOD /path`
   - **Auth**: (mechanism required)
   - **Path params**: table of name | type | description (if any)
   - **Query params**: table of name | type | required | default | description (if any)
   - **Request body**: table of field | type | required | description (or "None")
   - **Response (2xx)**: schema or table of field | type | description
   - **Error responses**: list of status code + meaning

   ## Events & Messages

   For each schema:
   ### `EventName`
   - **Direction**: produced / consumed
   - **Transport**: (Kafka topic, SQS queue, SNS topic, etc.)
   - **Fields**: table of field | type | required | description

   ## Webhooks
   (Document if present; otherwise omit this section)

   ## SDK / Public Interface
   List exported symbols with signatures and one-line descriptions.

   ## Environment Variables (caller-supplied)
   Table: name | type | default | description

   ## Authentication
   Full description of all auth mechanisms in use.

   ## Versioning
   How API versions are expressed and what the current version is.

   ## Flags & Ambiguities
   Bullet list of all items flagged `[UNDOCUMENTED — verify]`.

4. Call `store_note` with:
   - `key`: `integration-docs/<repo-name>`
   - `body`: the structured documentation from step 3
   - `tags`: `integration-docs,<repo-name>,api-documentation` plus relevant tags (e.g. `rest`, `events`, `grpc`, `webhooks`)

5. Confirm to the user: "Stored integration docs as `integration-docs/<repo-name>`."
