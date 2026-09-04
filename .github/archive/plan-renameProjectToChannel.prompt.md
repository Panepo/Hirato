## Plan: Rename "project" → "channel", Remove Shiratsuyu, Rename to "Hirato Secretary"

**TL;DR**: Replace every "project" concept with "channel" across the full stack, delete the Shiratsuyu external API integration (channels are now local-only: name + description), simplify Telegram commands to `/channel`, and rename the app to "Hirato Secretary".

---

## Phase 1 — Data Layer

1. **`app/memory/store.py`** — Rename `list_projects()` → `list_channels()`, `delete_project()` → `delete_channel()`, all `project_id` params → `channel_id`

2. **`app/memory/sessions.py`** — Rename SQLite column `project_id` → `channel_id`, index `idx_sessions_project` → `idx_sessions_channel`, rename Python methods (`get_sessions_for_project` → `get_sessions_for_channel`, etc.)

3. **`app/bot/telegram_sessions.py`** — Rename SQLite column `project_id` → `channel_id`

4. **Delete `app/memory/project_cache.py`** — Entire Shiratsuyu integration gone. No replacement needed; handlers will call `chroma_store.list_channels()` directly. Update `app/memory/__init__.py` to remove the import.

---

## Phase 2 — Agent Layer

5. **`app/agent/graph.py`** — `AgentState`: rename `project_id` → `channel_id`, remove `project_hint` field. Remove `project_resolver_node` from the graph wiring; wire `router_node` → `extractor_node` directly.

6. **`app/agent/nodes.py`** — Rename all `project_id` → `channel_id` refs, delete `project_resolver_node` function entirely, remove `project_cache` import.

7. **`app/agent/prompts.py`** — Remove `project_hint` extraction from `SPLITTER_PROMPT`; update "project" language → "channel".

---

## Phase 3 — API Layer

8. **`app/api/routes.py`**:
   - `POST /api/projects` → `POST /api/channels`, `GET /api/projects` → `GET /api/channels`, `DELETE /api/projects/{project_id}` → `DELETE /api/channels/{channel_id}`
   - Rename `NewProjectRequest` → `NewChannelRequest`
   - **Remove** `GET /api/shiratsuyu/projects` endpoint entirely
   - `ChatRequest.project_id` → `channel_id`
   - All local vars and error messages: "project" → "channel"

---

## Phase 4 — Telegram Bot

9. **`app/bot/handlers.py`** — Replace `/projects` + `/project` with single `/channel` command:
   - `/channel` *(no args)* → show inline keyboard of all channels
   - `/channel <name>` → fuzzy-find channel in `chroma_store.list_channels()` via `difflib`, set as active
   - `/channel new <name>` → create channel with that name (empty description), reply with confirmation
   - Rename `project_callback_handler` → `channel_callback_handler`

10. **`app/bot/bot.py`** — Update `BotCommand` list: remove `/projects`, add `/channel`

---

## Phase 5 — Config & Metadata

11. **`app/core/config.py`** — Remove `SHIRATSUYU_URL` and `SHIRATSUYU_BEARER`
12. **`pyproject.toml`** — `name = "hirato-secretary"`, update description
13. **`main.py`** — FastAPI title `"Hirato Secretary"`, remove any `project_cache` lifespan calls
14. **`README.md`** — Title + all "project" terminology → "channel", remove Shiratsuyu section

---

## Relevant Files

| File | Change |
|---|---|
| `app/memory/store.py` | Rename methods |
| `app/memory/sessions.py` | Schema column + method renames |
| `app/memory/project_cache.py` | **DELETE** |
| `app/memory/__init__.py` | Remove import |
| `app/bot/telegram_sessions.py` | Schema column rename |
| `app/bot/handlers.py` | Rewrite /channel command logic |
| `app/bot/bot.py` | Update BotCommand list |
| `app/agent/graph.py` | Rename field, remove resolver node |
| `app/agent/nodes.py` | Rename fields, delete resolver fn |
| `app/agent/prompts.py` | Remove project_hint from prompt |
| `app/api/routes.py` | Rename endpoints + models, remove Shiratsuyu |
| `app/core/config.py` | Remove SHIRATSUYU_* |
| `pyproject.toml` | Name + description |
| `main.py` | FastAPI title |
| `README.md` | Title + terminology |

---

## Verification

1. `grep -r "project" app/ --include="*.py" -i` → 0 concept hits
2. `grep -r "shiratsuyu" . --include="*.py" -i` → 0 hits
3. `python main.py` (or `uvicorn`) — no import errors
4. `POST /api/channels` creates a channel; `GET /api/channels` lists them
5. Telegram: `/channel` → list; `/channel foo` → selects "foo"; `/channel new testchan` → creates

---

## Decisions

- **SQLite migration**: `DROP TABLE` + recreate with new column names (simplest for dev). If live data must be preserved, `ALTER TABLE ... RENAME COLUMN` (SQLite 3.25+) can be used instead — let me know.
- **`/channel new <name>`**: description defaults to empty string via Telegram; REST API still accepts optional description.
- **Fuzzy match**: `difflib.get_close_matches()` in handlers directly against `chroma_store.list_channels()` — no cache layer.
- **Resolver node removed**: `channel_id` is always set explicitly (from Telegram session or API body) before the graph runs.

---

## Scope — Excluded

- `chroma_db/` directory — ChromaDB collection names are already arbitrary strings; existing data unaffected
- `deployment/` — no "project" concept in nginx/docker config
- `static/index.html` — frontend (out of scope unless it references "project" in API calls)
- No new features added beyond what's requested
