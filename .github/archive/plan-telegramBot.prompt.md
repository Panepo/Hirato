## Plan: Add Telegram Bot to Hirato

The bot will run in the **same process** as FastAPI via the async lifespan hook, reusing the existing `secretary_graph`, `SQLiteSessionStore`, and `ChromaStore` without any new infrastructure. Telegram users must authenticate with a one-time access code before they can interact with the bot.

---

**Steps**

### Phase 1 — Dependencies & Config
1. Add `python-telegram-bot>=21.0` to `requirements.txt`
2. Add to `app/core/config.py` `Settings` class:
   - `TELEGRAM_BOT_TOKEN: str = ""` (optional — bot only starts if set)
   - `TELEGRAM_ACCESS_CODE: str = ""` — shared secret users must enter to register; loaded from `.env`

### Phase 2 — Telegram Chat State Storage
3. Create `app/bot/__init__.py` (empty package marker)
4. Create `app/bot/telegram_sessions.py` — `TelegramSessionManager` class:
   - Adds two tables to the **existing** SQLite DB (same file as sessions):
     ```sql
     telegram_auth(
       chat_id   INTEGER PRIMARY KEY,
       authed_at TEXT NOT NULL          -- ISO timestamp of when auth was granted
     )
     telegram_chat_states(
       chat_id    INTEGER PRIMARY KEY,
       project_id TEXT,
       session_id TEXT,
       updated_at TEXT,
       FOREIGN KEY (chat_id) REFERENCES telegram_auth(chat_id) ON DELETE CASCADE
     )
     ```
   - Methods:
     - `initialize()` — create both tables
     - `is_authed(chat_id) -> bool`
     - `grant_auth(chat_id)` — insert into `telegram_auth`
     - `revoke_auth(chat_id)` — delete from `telegram_auth` (cascades state)
     - `get_state(chat_id) -> dict | None`
     - `set_state(chat_id, project_id, session_id)`
     - `clear_session(chat_id)` — nullify session_id only, keep project_id

### Phase 3 — Auth Guard Middleware
5. Create `app/bot/auth.py` — `require_auth` decorator / helper:
   - Wraps any handler coroutine; checks `telegram_session_manager.is_authed(chat_id)`
   - If not authed: replies with a prompt asking the user to run `/auth <code>` and returns early
   - Applied to every handler **except** `/start` and `/auth`

### Phase 4 — Bot Handlers
6. Create `app/bot/handlers.py` — handlers registered on the `Application`:
   - `/start` — welcome message explaining the bot; instructs unauthenticated users to `/auth <code>`; if already authed, shows project selection keyboard
   - `/auth <code>` — authentication handler:
     1. Compare provided code against `settings.TELEGRAM_ACCESS_CODE` using `hmac.compare_digest` (timing-safe)
     2. On match: call `grant_auth(chat_id)`, reply "✅ Authenticated! Use /projects to get started."
     3. On mismatch: reply "❌ Invalid code." (no further detail; no retry limit for now)
   - `/projects` *(auth required)* — show project selection as inline keyboard buttons
   - `/new` *(auth required)* — create a new session for the current project; error if no project selected
   - `/session` *(auth required)* — display current project & session info
   - `/logout` *(auth required)* — call `revoke_auth(chat_id)`, confirm revocation
   - `CallbackQueryHandler` *(auth required)* — handle inline project selection → `set_state`, confirm
   - `MessageHandler` plain text *(auth required)* — main flow:
     1. Guard: require project selected, else prompt `/projects`
     2. Resolve or create `session_id` via `SQLiteSessionStore`
     3. Send `ChatAction.TYPING` indicator
     4. Build `AgentState` identical to `app/api/routes.py` non-streaming path
     5. `await secretary_graph.ainvoke(state)`
     6. Persist user + assistant messages via `session_store.add_message()`
     7. Auto-generate title on first turn (same `TITLE_PROMPT` logic as in routes.py)
     8. Reply with final combined response

### Phase 5 — Bot Application Lifecycle
7. Create `app/bot/bot.py`:
   - `build_application(token)` — creates `telegram.ext.Application`, registers all handlers
   - `start_bot(application)` / `stop_bot(application)` — async helpers using `application.initialize()` → `application.start()` → `application.updater.start_polling()` (and reverse on stop)

### Phase 6 — FastAPI Lifespan Integration
8. Modify `main.py` lifespan:
   - After `await session_store.initialize()`, also `await telegram_session_manager.initialize()`
   - If `settings.TELEGRAM_BOT_TOKEN` is set → build + start bot
   - On shutdown → stop bot gracefully
   - Bot is **fully optional**: the web interface works unchanged if token is not set

---

**Relevant Files**
- `requirements.txt` — add `python-telegram-bot>=21.0`
- `app/core/config.py` — add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ACCESS_CODE`
- `app/bot/__init__.py` — new (empty)
- `app/bot/telegram_sessions.py` — new, SQLite auth + state management
- `app/bot/auth.py` — new, `require_auth` guard
- `app/bot/handlers.py` — new, all Telegram command/message handlers
- `app/bot/bot.py` — new, Application builder + lifecycle helpers
- `main.py` — extend lifespan to init auth tables + start/stop bot

**Reused Without Changes**
- `app/agent/graph.py` → `secretary_graph` (invoked directly)
- `app/memory/sessions.py` → `SQLiteSessionStore` (same shared instance)
- `app/memory/store.py` → `ChromaStore` (same shared instance)
- `app/memory/project_cache.py` → `project_cache` (same cache)
- `app/api/routes.py` → reference pattern for `AgentState` construction

---

**Auth Flow (user-facing)**
```
User sends any message (unauthenticated)
  → Bot: "You need to authenticate first. Send /auth <code>"

User sends /auth mySecret
  → Bot compares with TELEGRAM_ACCESS_CODE via hmac.compare_digest
  → Match:    "✅ Authenticated! Use /projects to get started."
  → No match: "❌ Invalid code."

Authenticated user sends /projects
  → Inline keyboard with project buttons

User taps a project button
  → "✅ Project set to: hirato. Send a message to start!"

User sends a message
  → Typing indicator → Agent graph → Response
```

---

**Verification**
1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ACCESS_CODE` in `.env`, start the server — confirm no startup errors
2. Send any message without auth → confirm "authenticate first" prompt
3. Send `/auth wrongcode` → confirm "❌ Invalid code."
4. Send `/auth <correct code>` → confirm "✅ Authenticated"
5. `/projects` → select a project via inline button → confirm state persisted
6. Send a message → confirm typing indicator and real agent response
7. `/new` → confirm new `session_id` created in SQLite
8. `/logout` → confirm `telegram_auth` row deleted; subsequent messages blocked again
9. Omit `TELEGRAM_BOT_TOKEN` from `.env` — confirm web interface still works normally (bot skipped)

---

**Decisions**
- **Same process, no new infra** — bot polling runs as an asyncio task alongside uvicorn
- **`python-telegram-bot` v21+** — async-native, matches existing `asyncio`/`httpx` patterns
- **No streaming to Telegram** — Telegram rate limits make token-by-token edits impractical; typing indicator + full response is the right UX
- **State in existing SQLite DB** — no new DB file, just two new tables
- **Shared access code auth** — single `TELEGRAM_ACCESS_CODE` in `.env`; simple and sufficient for a private/team tool. Can be upgraded to per-user codes or token-based auth later
- **`hmac.compare_digest`** — timing-safe comparison prevents timing-oracle attacks on the access code

**Further Considerations**
1. **Webhook vs. polling**: Polling is simpler to set up (no public HTTPS endpoint needed). If this is deployed behind nginx (already present), a webhook endpoint could be added as `/telegram/webhook` to avoid polling overhead. Recommend polling for now unless you want webhook.
2. **Multi-user isolation**: Each Telegram `chat_id` gets its own auth record, project, and session state. Group chats would share one state per group — acceptable behavior?
3. **Rate-limiting `/auth` attempts**: Currently no limit. Could add a `telegram_auth_attempts(chat_id, attempt_count, last_attempt_at)` table and block after N failures if needed.
