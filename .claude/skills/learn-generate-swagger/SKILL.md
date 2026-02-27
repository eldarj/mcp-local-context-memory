---
name: learn-generate-swagger
description: Read the REST API codebase and generate a valid static OpenAPI 3.0 YAML spec, stored as a file with a summary note.
---

Generate an OpenAPI 3.0 specification for the REST API in the current repo.

## Default Acceptance Criteria

Apply these criteria to every endpoint and schema in the spec. Do not skip or approximate any of them:

- Every endpoint must have: `operationId` (camelCase, globally unique), `summary` (one sentence), `tags` (at least one), `parameters` (all path/query/header params with schema and `required`), `requestBody` (if the method accepts a body), and at least one `responses` entry.
- All request/response schemas that appear in more than one place must use `$ref: '#/components/schemas/...'` — never inline duplicate schemas.
- All authentication schemes must be declared in `components/securitySchemes` and referenced via `security` at the operation or global level.
- The spec must use OpenAPI 3.0.x — not Swagger 2.x. The document must begin with `openapi: "3.0.3"`.
- All enum values must be listed explicitly in the schema (`enum: [value1, value2, ...]`) — no free-form strings where a fixed set is known from the source code.
- Every endpoint must document its 4xx and 5xx error responses with at least a `description`. Use `$ref` for standard error schemas (e.g. `#/components/schemas/ErrorResponse`) wherever the same shape is reused.
- Any field, parameter, or behaviour whose type or optionality is ambiguous in the source must be annotated with `x-ambiguous: true` and an inline comment explaining the uncertainty.

## Steps

1. Identify the current repo:
   - Run `git rev-parse --show-toplevel` to get the repo root.
   - Extract the repo name.

2. Discover all REST endpoints and schemas by reading the source:
   - All HTTP methods and paths (route definitions)
   - Request body shapes and query/path/header parameters
   - Response shapes and status codes for each endpoint
   - Reusable models (Pydantic models, TypeScript interfaces, Go structs, etc.)
   - Authentication and security schemes in use
   - Any versioning prefix (e.g. `/api/v1`)

3. Generate a complete OpenAPI 3.0.3 YAML document applying all acceptance criteria above.

   Minimum required structure:
   ```yaml
   openapi: "3.0.3"
   info:
     title: <service name>
     version: "1.0.0"
     description: <one paragraph>
   servers:
     - url: <base URL if known, otherwise use a placeholder>
   paths:
     /path:
       get:
         operationId: ...
         summary: ...
         tags: [...]
         parameters: [...]
         responses:
           "200":
             description: ...
             content:
               application/json:
                 schema:
                   $ref: '#/components/schemas/...'
   components:
     schemas: {}
     securitySchemes: {}
   ```

4. Write the YAML to a temporary file:
   ```bash
   cat > /tmp/<repo-name>-openapi.yaml << 'EOF'
   <yaml content>
   EOF
   ```
   Then base64-encode it:
   ```bash
   base64 -w 0 /tmp/<repo-name>-openapi.yaml
   ```

5. Call `store_file` with:
   - `name`: `swagger/<repo-name>.yaml`
   - `content_base64`: the base64 string from step 4
   - `mime_type`: `application/yaml`
   - `tags`: `swagger,openapi,<repo-name>`

6. Call `store_note` with:
   - `key`: `swagger/<repo-name>`
   - `body`: a markdown summary containing:
     - One-line description of what the API does
     - Total number of endpoints documented
     - List of tags used in the spec (each tag = a logical group of endpoints)
     - Any items flagged with `x-ambiguous: true`
     - Reference line: "Full spec stored at file `swagger/<repo-name>.yaml`"
   - `tags`: `swagger,openapi,<repo-name>`

7. Confirm to the user: "Stored OpenAPI spec as `swagger/<repo-name>.yaml` and summary note as `swagger/<repo-name>`."
