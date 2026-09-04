# Plan: Shiratsuyu Auth + Channel RBAC + Vue 3 Frontend Migration

## Context / Decisions (confirmed with user)
- Site admin = Shiratsuyu `usergroups` contains a new `HIRATO_MASTER` role id (Shiratsuyu will add it). Hirato stores this id as a config setting `SITE_ADMIN_ROLE_ID` (placeholder default, adjustable once Shiratsuyu confirms the real int).
- Channel-level roles (viewer/writer/manager) are Hirato-local concepts, NOT in Shiratsuyu's Role enum. Stored in new local SQLite tables (new `app/memory/auth_store.py`), not LanceDB.
- Token validation: Hirato will share Shiratsuyu's `JWT_SECRET` (user adding to .env) and verify JWT signature locally (HS256) — no per-request network call to Shiratsuyu. JWT payload only has `sub`+`hex` (per docs), so full user info (name, usergroups) is cached locally in Hirato's `users` table at login time (`POST /auth` response) and re-synced only on next login (no periodic refresh — acceptable per user, noted as a limitation).
- Closed channels are **fully hidden**: excluded from `GET /api/channels` list, and direct access by unauthorized users returns 404 (not 403) to avoid leaking existence.
- Channel creation: **site-admin only**. Deletion: assumed site-admin only (destructive/global action, not explicitly asked — flagged as assumption). No auto-manager-on-create; site admin assigns a manager afterward via a separate endpoint.
- Telegram: **fully read-only (viewer-level) everywhere** — cannot trigger `save_memory` (progress report writes) at all, regardless of channel. Keeps existing `TELEGRAM_ACCESS_CODE` gate unchanged, but channel listing/selection is restricted to **open** channels only, and the `/channel new <name>` command is removed (channel creation now site-admin-only via web).
- Frontend: Vite + Vue 3 + TS scaffolded in new `frontend/` dir, built output served by FastAPI (replaces `static/index.html` mount). Vite dev server proxies `/api` to FastAPI locally.

## Phase A — Backend: Shiratsuyu login + identity cache
*(independent of Phase D, blocks B/C/E-G)*
1. `app/core/config.py`: add `SHIRATSUYU_BASE_URL`, `SHIRATSUYU_SERVER_NAME="hirato"`, `JWT_SECRET`, `JWT_ALGORITHM="HS256"`, `SITE_ADMIN_ROLE_ID: int` (placeholder), `AUTH_DB_PATH="./auth.db"`.
2. Add `PyJWT` to `requirements.txt` and `pyproject.toml` dependencies.
3. New `app/memory/auth_store.py` (aiosqlite, mirrors `app/memory/sessions.py` / `telegram_sessions.py` patterns):
   - `init_db()`: tables `users(id PK, name, usergroups TEXT json, updated_at)`, `channel_settings(channel_id PK, is_open INTEGER DEFAULT 1, created_at)`, `channel_roles(channel_id, user_id, role CHECK IN ('viewer','writer','manager'), PRIMARY KEY(channel_id,user_id))`.
   - `upsert_user`, `get_user`, `is_channel_open` (default True if no row), `set_channel_open`, `ensure_channel_settings_row`, `delete_channel_settings`, `get_channel_role`, `set_channel_role`, `remove_channel_role`, `list_channel_roles(channel_id)`, `list_open_channel_ids()`.
   - Call `auth_store.init_db()` in `main.py` lifespan alongside `sessions_store.init_db()`.
4. New `app/core/auth.py`:
   - `shiratsuyu_login(email, password) -> dict` — httpx POST `{SHIRATSUYU_BASE_URL}/auth` with `server=SHIRATSUYU_SERVER_NAME`; maps upstream 401/404/400 to matching HTTPException.
   - `decode_token(token) -> dict` via `jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])`, raising 401 on `jwt.PyJWTError`.
   - `AuthUser` pydantic model: `id, name, usergroups: list[int]`.
   - `get_current_user(authorization: str = Header(None)) -> AuthUser` FastAPI dependency: parse `Bearer <token>`, decode, look up cached row via `auth_store.get_user(sub)`; 401 if missing/invalid.
   - `is_site_admin(user) -> bool` = `SITE_ADMIN_ROLE_ID in user.usergroups`.
   - `require_site_admin(user=Depends(get_current_user))` dependency raising 403.
5. New `app/api/auth_routes.py` (separate router, included in `main.py`):
   - `POST /api/auth/login` — body `{email, password}`, calls `shiratsuyu_login`, `auth_store.upsert_user(...)`, returns Shiratsuyu's response verbatim.
   - `GET /api/auth/me` — returns `{id, name, usergroups, is_site_admin}` for `Depends(get_current_user)`.

## Phase B — Backend: Channel ACL + route gating
*(depends on Phase A)*
6. New `app/core/channel_acl.py`:
   - `get_effective_role(channel_id, user) -> "admin"|"manager"|"writer"|"viewer"|None`.
   - `require_channel_view(channel_id, user)`: 404 if channel missing; if open → any authed user passes; if closed → needs role or admin, else **404** (hide existence).
   - `require_channel_write(channel_id, user)`: needs writer/manager/admin else 403 (used for memory browser list/edit/delete/import AND for chat's `save_memory` path).
   - `require_channel_manage(channel_id, user)`: needs manager/admin else 403 (viewer/writer assignment, open/closed toggle).
7. `app/api/routes.py`: add `Depends(get_current_user)` to every endpoint (auth required site-wide). Apply guards:
   - `GET /api/channels`: return `list[dict]` `{channel_id, is_open, role}` filtered to open OR user has a role OR is_site_admin (fully hidden otherwise). **Breaking response-shape change** from `list[str]`.
   - `POST /api/channels`: `require_site_admin`; on success call `auth_store.ensure_channel_settings_row(channel_id)`.
   - `DELETE /api/channels/{channel_id}` (both variants): `require_site_admin`; also `auth_store.delete_channel_settings`.
   - `GET/PUT/DELETE /api/channels/{channel_id}/memories*`, `/memories/import`, `/import/json`, `/import/documents`: `require_channel_write` (memory browser view+edit both gated, per spec).
   - `/api/sessions*`: resolve `channel_id` (from body for list/create; from stored session row for get/delete/rename) then `require_channel_view`.
8. New endpoints in `app/api/routes.py` (or new `app/api/channel_admin_routes.py`):
   - `PUT /api/channels/{channel_id}` body `{is_open: bool}` — `require_channel_manage`.
   - `POST/DELETE /api/channels/{channel_id}/managers[/{user_id}]` — `require_site_admin`.
   - `POST/DELETE /api/channels/{channel_id}/viewers[/{user_id}]` and `/writers[/{user_id}]` — `require_channel_manage`.
   - `GET /api/channels/{channel_id}/roles` — `require_channel_manage`; lists current manager/writer/viewer assignments.
9. Restructure `POST /api/chat` to compose nodes manually (mirror `/api/chat/stream`'s existing pattern): call `router_node_async` first → `require_channel_view` always → if `decision == "save_memory"`, additionally check write access (403 if not writer/manager/admin) → then run `extractor_node_async`/`store_node_async` or `retriever_node_async`/`answer_node_async` accordingly. Stop using `secretary_graph.ainvoke` for this endpoint (avoids double router call, allows gating before any write). Apply the same write-gate check in `/api/chat/stream` right after its existing `router_node_async` call, before `extractor_node_async`.

## Phase C — Backend: Telegram restrictions
*(depends on Phase B for `is_open`/roles; can run parallel with Phase D)*
10. `app/bot/handlers.py`:
    - Filter `vector_store.list_channels()` results everywhere they're listed (`start_handler`, `channel_handler` fuzzy/substring match + keyboard, `_build_channel_keyboard` call sites) through `auth_store.list_open_channel_ids()`.
    - Remove the `/channel new <name>` creation branch entirely (site-admin-only now, not available via Telegram).
    - `message_handler`: replace single `secretary_graph.ainvoke(agent_state)` call with manual composition — run `router_node_async` (from `app/agent/node_async.py`); if `decision != "answer_question"`, reply with a fixed message ("Progress report logging isn't available via Telegram — please use the web app.") and return without touching extractor/store; else run `retriever_node_async` + `answer_node_async` and reply with the result. Guarantees Telegram never reaches `store_node`.

## Phase D — Frontend scaffold
*(independent, start any time)*
11. Scaffold `frontend/` via Vite `vue-ts` template; add `vue-router`, `pinia`. Configure `vite.config.ts`: dev-server proxy `/api` → `http://localhost:7950`, build output → `frontend/dist`.
12. `src/api/client.ts`: fetch/axios wrapper attaching `Authorization: Bearer <token>` from the auth store; global 401 handler redirects to `/login`.
13. Pinia stores: `stores/auth.ts` (token, user, `login()`, `logout()`, `isSiteAdmin`, persisted to localStorage), `stores/channels.ts` (list, current channel, role).

## Phase E — Frontend: Auth shell
*(depends on Phase A/B APIs + Phase D)*
14. `views/LoginView.vue` — email/password form → `POST /api/auth/login` → populate auth store → redirect.
15. `router/index.ts` navigation guard redirecting unauthenticated users to `/login`; `components/TopBar.vue` / layout shell ported from `static/index.html`'s `#topbar`/`#main-layout`/`#sidebar` structure and CSS.

## Phase F — Frontend: Channel & chat pages
*(depends on Phase E)*
16. `views/ChannelListView.vue` — channel switcher; "New channel" action visible only when `isSiteAdmin`.
17. `views/ChatView.vue` + `components/SessionSidebar.vue` + `composables/useChatStream.ts` — port the SSE `fetch`-stream parsing (`token`/`metrics`/`session`/`done` event types) and message-bubble rendering from `static/index.html` lines ~1036-1970 (`renderSessionEntry`, `createBubble`, `appendBubble`, `appendStreamingBubble`, etc.).
18. `views/MemoryBrowserView.vue` (+ `MemoryList.vue`, `MemoryDetailPanel.vue`, `MemoryEditModal.vue`) — port list/detail/edit/bulk-delete/group-by-source/tag rendering (index.html `renderMemoryItem`, `renderMemoryGroup`, `groupReferenceDocsBySource`, edit-mode functions). Route meta requires writer/manager/admin (backend still enforces via 403; frontend just hides the nav entry / shows a friendly message).
19. `components/ImportDocumentsPanel.vue` — port multi-file upload + progress/indexing-overlay UI.

## Phase G — Frontend: Channel admin page
*(depends on Phase F + Phase B step 8 endpoints)*
20. `views/ChannelAdminView.vue` — open/closed toggle (manager+), manager assignment section (site-admin only, uses `/managers`), viewer/writer assignment section (manager+, uses `/viewers`/`/writers`/`/roles`).

## Phase H — Cutover & cleanup
*(depends on all above)*
21. `main.py`: remove `StaticFiles(directory="static", html=True)` mount; serve `frontend/dist` assets + a catch-all GET route returning `frontend/dist/index.html` for any non-`/api` path (SPA history-mode fallback).
22. Manual full-flow smoke test across all role levels, then delete `static/index.html` once parity is confirmed.

## Relevant files
- `app/core/config.py` — new settings (step 1).
- `requirements.txt`, `pyproject.toml` — add `PyJWT` (step 2).
- `app/memory/auth_store.py` — new file, users/channel_settings/channel_roles (step 3).
- `app/core/auth.py` — new file, JWT decode + `get_current_user`/`is_site_admin` (step 4).
- `app/api/auth_routes.py` — new file, login/me endpoints (step 5).
- `app/core/channel_acl.py` — new file, role/visibility guards (step 6).
- `app/api/routes.py` — add auth deps + guards to all existing endpoints; restructure `/api/chat`; add admin endpoints (steps 7-9).
- `app/agent/node_async.py` — reused as-is (`router_node_async`, `extractor_node_async`, `store_node_async`, `retriever_node_async`, `answer_node_async`/`answer_node_astream`); no changes needed, just composed differently by callers.
- `app/bot/handlers.py` — channel filtering, remove `/channel new`, rework `message_handler` (step 10).
- `main.py` — `auth_store.init_db()` in lifespan (step 3); static mount replaced by SPA serving (step 21).
- `frontend/` — new Vite project (steps 11-20); mirrors `static/index.html` (chat/session sidebar/memory browser/import UI logic to port).
- `static/index.html` — source of truth for UI/behavior to port, deleted at the end (step 22).

## Verification
1. Backend: run `.venv\Scripts\python.exe -m pytest` — no regressions in `tests/test_*.py`.
2. Manually `curl`/httpx `POST /api/auth/login` against a real/staging Shiratsuyu instance; confirm token decodes locally and `GET /api/auth/me` returns expected `is_site_admin`.
3. Create an open + a closed channel; confirm closed channel is absent from `GET /api/channels` for a plain viewer, and `GET /api/channels/{id}` (or memories) returns 404 for that user.
4. As a viewer (no writer/manager role), send a progress-report-shaped chat message → expect 403 from `/api/chat` and `/api/chat/stream`; as a writer, same message should succeed and appear in the memory browser.
5. Telegram: confirm `/channel` lists only open channels, `/channel new` no longer works, and sending a report-like message replies with the "not available via Telegram" message instead of saving to LanceDB.
6. Frontend: `npm run build` (no TS errors) and `npm run dev` against the running backend — click through login → channel list → chat (verify streaming) → memory browser (edit/delete/import) → admin page, for site-admin, manager, writer, and viewer accounts.

## Further considerations
1. `SITE_ADMIN_ROLE_ID`'s real integer value depends on Shiratsuyu's not-yet-added `HIRATO_MASTER` enum entry — kept as an env-configurable setting with a placeholder default so it can be updated once confirmed, rather than hardcoded.
2. Local user/role cache only refreshes on login (no periodic re-sync with Shiratsuyu) — a role change on Shiratsuyu's side won't take effect for an already-logged-in Hirato session until they log in again. Acceptable per current design; could add a TTL-based re-check later if needed.
3. Channel deletion was assumed site-admin-only (destructive/global action) by analogy with creation — flag if a different rule (e.g. manager-can-delete-own-channel) is wanted.
