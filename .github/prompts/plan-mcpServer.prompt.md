# Plan: MCP server exposing all API functions, gated by login

## Context gathered
- FastAPI app (`main.py`) mounts `app/api/routes.py` (`/api/*`, channels/memories/sessions/chat) and `app/api/auth_routes.py` (`/api/auth/*`).
- Auth model: JWT bearer. `POST /api/auth/login` (auth_routes.py) calls `shiratsuyu_login()` (app/core/auth.py), resolves usergroups/empno, `auth_store.upsert_user()`, returns Shiratsuyu's raw JSON (contains a JWT signed with the shared `settings.JWT_SECRET`). `get_current_user()` decodes the bearer token + looks up cached user via `auth_store.get_user()`. Role checks: `is_site_admin`, `is_site_manager`, `require_site_admin`, `require_channel_creator` (app/core/auth.py); `get_effective_role`, `require_channel_view/write/manage` (app/core/channel_acl.py) — all are plain async functions taking `(channel_id, user)`/`(user)`, callable directly (the `Depends(...)` defaults are irrelevant when called with an explicit `user` arg).
- Existing analogous pattern: `app/bot/telegram_sessions.py` (`TelegramSessionManager`, sqlite-backed "is this chat_id authed") + `app/bot/auth.py`'s `require_auth` decorator gating Telegram handlers — this is the template to mirror for MCP, but in-memory (not persisted) since MCP connections are ephemeral, keyed per MCP session instead of per chat_id.
- No `mcp` dependency currently in pyproject.toml/requirements.txt.
- MCP Python SDK (`modelcontextprotocol/python-sdk`) research: current API surface is `mcp.server.mcpserver.MCPServer` (renamed from v1's `FastMCP`), with `@mcp.tool()` decorator, and a `Context` param (`mcp.server.mcpserver.Context`) injectable into tool functions for per-request info; `Context.session` gives access to the underlying session object (usable as an identity key for our own per-connection auth map). Mounting into an existing ASGI app (FastAPI/Starlette) via `app.mount("/mcp", mcp.streamable_http_app(json_response=True, streamable_http_path="/"))`, **but the mounted sub-app's own lifespan never runs** — the host app's lifespan (main.py's `lifespan()`) MUST additionally enter `async with mcp.session_manager.run():` around the `yield`, and `mcp.session_manager` only exists after `streamable_http_app()` has been called (call it at module level, touch `.session_manager` only inside lifespan). Browser/JS clients need CORS `expose_headers=["Mcp-Session-Id"]` and allow `Mcp-*` request headers.
- Confirmed via user Q&A: mount into existing FastAPI app (not stdio), wrap literally every REST endpoint (incl. destructive/admin), login tool takes email+password directly (mirrors `/api/auth/login`), chat/regenerate tools return full final text only (no MCP-side streaming).

**Approach**: Add `mcp` SDK, build a new `app/mcp/` package with a `MCPServer` instance mounted at `/mcp` in `main.py`. Add an in-memory `McpAuthSessionManager` keyed by the MCP connection's session identity, populated by a `login` tool (reuses `shiratsuyu_login` + `auth_store.upsert_user`, refactored into a shared helper). Every other tool starts with a `_require_user(ctx)` guard that looks up the stored `AuthUser` or raises a clear "call login first" tool error. Tools reuse existing store/auth functions directly (no HTTP round-trip) — for `chat`/`chat_regenerate` and document import, extract the orchestration logic that's currently inline in `routes.py` into small shared service functions so both REST and MCP call the same code (avoids duplicating ~40-80 lines of node-orchestration and file-handling logic).

**Steps**

### Phase 0 — Dependency & scaffolding (no dependents)
1. Add `mcp` to `pyproject.toml` dependencies and `requirements.txt` (unpinned, matching repo convention).
2. Create `app/mcp/__init__.py` (empty) and `app/mcp/session.py`: `McpAuthSessionManager` class — in-memory `dict[Any, AuthUser]` keyed by `id(ctx.session)` (verify the actual stable per-connection identity attribute on `Context`/`ServerSession` while implementing this file — the SDK exposes `ctx.session` for "advanced usage"; confirm nothing better like a `session_id` property exists on the installed version before committing to `id(...)`). Methods: `login(key, user: AuthUser) -> None`, `get(key) -> AuthUser | None`, `logout(key) -> None`.

### Phase 1 — Shared business-logic extraction (*depends on nothing, can run parallel with Phase 0*)
Refactor inline logic out of `app/api/routes.py` / `app/api/auth_routes.py` into reusable functions, then update those routes to call the extracted functions (behavior-preserving refactor, verify via existing tests + manual smoke test after).
3. `app/core/auth.py`: extract `perform_login(email, password) -> AuthUser` containing the empno/usergroups resolution + `auth_store.upsert_user()` call currently inline in `auth_routes.login()` (keep `shiratsuyu_login()`'s raw dict return separately for the REST response body, since REST callers want the raw token payload too — `perform_login` should return `(raw_result: dict, user: AuthUser)` so REST still returns the original JSON while MCP just needs the `AuthUser`).
4. New `app/agent/chat_service.py`: extract the state-machine orchestration duplicated across `chat()`, `chat_stream()`, `chat_regenerate()` in routes.py into:
   - `run_chat_turn(channel_id, session_id, message, user) -> ChatResponse`-shaped dict (mirrors current `chat()` body, non-streaming, using `answer_node_async`).
   - `run_regenerate_turn(channel_id, session_id, user) -> dict` (new: mirrors `chat_regenerate()`'s prep steps — delete last assistant message, rerun router/extractor/store/retriever nodes — but finishes with non-streaming `answer_node_async` + persistence + title, like `run_chat_turn`, instead of the SSE generator).
   Update `routes.py`'s `chat()` to call `run_chat_turn` (behavior-identical); leave `chat_stream`/`chat_regenerate` REST endpoints as-is (still SSE) but have them delegate shared prep where straightforward.
5. New `app/services/document_import.py`: extract the temp-file-write + extension-allowlist + `IndexerClient().process_document()` + `vector_store.import_chunks()` logic from `import_documents()` into `import_document_bytes(channel_id, filename, content: bytes) -> dict` (single-file variant), and a thin `import_embedded_json_bytes(channel_id, content: bytes) -> dict` wrapping the JSON-parsing + validation from `import_embedded_json()`. Update both routes to call these.

### Phase 2 — MCP server & tools (*depends on Phase 0, 1*)
6. `app/mcp/server.py`: build `mcp = MCPServer("Hirato Secretary")`. Define `_require_user(ctx) -> AuthUser` helper: looks up `mcp_sessions.get(<key>)`, raises a descriptive error (e.g. `ValueError("Not logged in — call the login tool first.")`) if absent — MCP framework surfaces this as a tool-call error to the client, not a crash.
7. Auth tools: `login(email, password, ctx)` (calls `perform_login`, stores in `mcp_sessions`, returns `{id, name, usergroups}`), `whoami(ctx)` (mirrors `/api/auth/me`), `logout(ctx)`.
8. Channel tools (reuse `vector_store`, `auth_store`, `get_effective_role`, `is_site_admin`, `is_site_manager` directly, replicating each route's permission check inline): `list_channels`, `create_channel`, `delete_channel`, `update_channel_settings`, `list_channel_roles`, `add_manager`, `remove_manager`, `add_writer`, `remove_writer`, `add_viewer`, `remove_viewer`.
9. Memory tools: `list_memories`, `delete_memories`, `delete_memory`, `update_memory`, `import_memories`, `import_embedded_json` (base64-encoded `content` string param, decode + call `import_embedded_json_bytes`), `import_documents` (accepts `files: list[{filename: str, content_base64: str}]`, decodes each, calls `import_document_bytes` per file, aggregates same `imported/skipped/failed` shape as the REST route).
10. Session tools: `list_sessions`, `create_session`, `get_session`, `delete_session`, `rename_session`.
11. Chat tools: `chat(message, channel_id, session_id, ctx)` → calls `run_chat_turn`; `chat_regenerate(channel_id, session_id, ctx)` → calls `run_regenerate_turn`.
12. Misc: `query_user(identifier, ctx)` → wraps `shiratsuyu_query_user`.

### Phase 3 — Mounting (*depends on Phase 2*)
13. `main.py`: import the built `mcp` server, mount via `app.mount("/mcp", mcp.streamable_http_app(json_response=True, streamable_http_path="/"))` at module level (after `app = FastAPI(...)`, before/after existing `include_router` calls — order doesn't matter for mounts vs routers). Wrap the existing `lifespan()` body's `yield` with `async with mcp.session_manager.run():` so the mounted sub-app's session manager actually starts (mounted lifespans never run per SDK docs).
14. Update the existing `CORSMiddleware` call in main.py to add `expose_headers=["Mcp-Session-Id"]` (needed for browser-based MCP clients to read the session id).

**Relevant files**
- `pyproject.toml`, `requirements.txt` — add `mcp` dependency.
- `app/mcp/session.py` (new) — `McpAuthSessionManager`.
- `app/mcp/server.py` (new) — MCPServer instance + all tool definitions.
- `app/core/auth.py` — add `perform_login()`, reused by both auth_routes and MCP login tool.
- `app/api/auth_routes.py` — update `login()` to call `perform_login()`.
- `app/agent/chat_service.py` (new) — `run_chat_turn()`, `run_regenerate_turn()`.
- `app/api/routes.py` — update `chat()` to call `run_chat_turn()`; reference for exact permission-check patterns to replicate in MCP tools.
- `app/services/document_import.py` (new) — `import_document_bytes()`, `import_embedded_json_bytes()`.
- `app/api/routes.py` — update `import_documents()`/`import_embedded_json()` to call the new service functions.
- `main.py` — mount MCP app, extend lifespan, CORS `expose_headers`.

**Verification**
1. Run existing suite: `.venv\Scripts\python.exe -m pytest` (per repo memory note, run bare — don't pipe through `Select-Object`) — confirm no regressions from the routes.py refactors.
2. Manual REST smoke test: hit `/api/auth/login`, `/api/chat`, `/api/channels/{id}/import/json` to confirm behavior is unchanged after extraction.
3. Manual MCP smoke test: use an MCP client (or raw JSON-RPC over `streamable-http` via curl/httpx, capturing `Mcp-Session-Id` from the first response) against `http://127.0.0.1:7950/mcp` (or `/hirato/mcp` if `ROOT_PATH` applies) — call `login` with real/test credentials, confirm a subsequent `list_channels` call succeeds using the same session id, and confirm it fails with a clear error when called *before* `login` or with a fresh/different session id.
4. Confirm destructive tools (`delete_channel`, `remove_manager`, etc.) enforce the same 403-equivalent (raised error) behavior as their REST counterparts for an under-privileged logged-in user.

**Decisions**
- MCP session persists only in-memory (not in sqlite) — acceptable since MCP client connections are inherently ephemeral (matches how `/api` bearer tokens already work; nothing new to persist across server restarts).
- `chat`/`chat_regenerate` MCP tools return the complete final answer in one response (no incremental streaming), per user confirmation — simpler and matches the tool call/response model.
- Every REST endpoint gets a 1:1 MCP tool, including destructive/admin-only ones, per user confirmation — MCP tools replicate the exact same permission checks as their REST counterparts, just invoked in-process against the session-stored `AuthUser` instead of via `Depends()`.
- File-based import tools (`import_documents`, `import_embedded_json`) take base64-encoded content as a tool argument (JSON-RPC has no multipart upload).

**Further Considerations**
1. Exact stable "per-connection identity" API on the installed `mcp` package version is not 100% confirmed from docs alone (only that `Context.session` gives "access to the underlying session for advanced usage") — Phase 0 step 2 includes a quick empirical check (print/inspect the `Context`/session object) before committing to `id(ctx.session)` as the dict key.
2. The `mcp` SDK recently renamed `FastMCP` → `MCPServer` (v1→v2 migration) — implementation should target whatever API is present in the actually-installed version (check `python -c "import mcp; print(mcp.__version__)"` and adjust import paths if an older v1-style `mcp.server.fastmcp.FastMCP` gets installed instead).
