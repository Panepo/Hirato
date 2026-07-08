# Plan: Chat History System

Build a persistent chat history system with a left sidebar listing past conversations, a "New Chat" button, and automatic title generation using the LLM.

---

## Architecture

### Storage: SQLite (new `app/memory/sessions.py`)
Two tables:
- `sessions(id TEXT PK, project_id TEXT, title TEXT, created_at, updated_at)`
- `messages(id TEXT PK, session_id TEXT FK, role TEXT, content TEXT, timestamp)`

SQLite is local, no new infrastructure, complements existing ChromaDB.

### Title generation: LLM call after first complete exchange
New `TITLE_PROMPT` in `app/agent/prompts.py`. Call `chat_llm` once, update session title in DB.

### Session flow:
- On "New Chat" click or first message → `POST /api/sessions` → returns `session_id`
- Every `POST /api/chat` includes `session_id` → saves messages → triggers title gen on first exchange
- Sidebar lists `GET /api/sessions?project_id=X` and loads messages on click

---

## Phase 1: Backend — Session Store

1. **Create `app/memory/sessions.py`** — `SQLiteSessionStore` class with async methods:
   - `init_db()` — creates two tables: `sessions` and `messages`
   - `create_session(project_id)` → returns new session dict
   - `list_sessions(project_id)` → list ordered by `updated_at DESC`
   - `get_session(session_id)` → session metadata + messages list
   - `delete_session(session_id)` → cascades to messages
   - `add_message(session_id, role, content)` → persists message
   - `get_messages(session_id)` → ordered list
   - `update_title(session_id, title)` → sets title + bumps `updated_at`
   - Uses `aiosqlite` for async compatibility with FastAPI

2. **Update `app/core/config.py`** — add `SESSIONS_DB_PATH: str = "./sessions.db"`

3. **Update `main.py`** — call `sessions_store.init_db()` in a startup handler

---

## Phase 2: Backend — Session API Endpoints

4. **Add to `app/api/routes.py`**:
   - `GET /api/sessions?project_id=X` → list sessions ordered by `updated_at DESC`
   - `POST /api/sessions` body `{project_id}` → create and return new session
   - `GET /api/sessions/{session_id}` → metadata + full `messages[]`
   - `DELETE /api/sessions/{session_id}` → delete session and all its messages
   - `PUT /api/sessions/{session_id}/title` body `{title}` → manual rename

5. **Modify `POST /api/chat`**:
   - Add optional `session_id: str | None` to `ChatRequest`
   - Load prior messages from DB, prepend to `AgentState.messages` for conversational context
   - After agent responds: persist both `user` and `assistant` messages to DB
   - Update `sessions.updated_at`
   - If session title is still `None`: trigger title generation (Phase 3), store result
   - Return `session_id` and optional `title_updated: bool` alongside `response`

---

## Phase 3: Backend — Auto Title Generation

6. **Add `TITLE_PROMPT` to `app/agent/prompts.py`**:
   - System: "Generate a concise 4–7 word title for this conversation. Return only the title text, no quotes."
   - User: first user message content

7. **Add `generate_title(message: str) -> str`** helper in `app/api/routes.py` — single `chat_llm` call with `TITLE_PROMPT`, result stored via `update_title()`

---

## Phase 4: Frontend — Sidebar + Session Logic

8. **Restructure `static/index.html` layout**:
   - Outer flex container: left sidebar (fixed width, dark background) + right chat panel (existing content, unchanged)
   - Sidebar contains:
     - "New Chat" button at top
     - Scrollable session list (title + relative date)
     - Active session highlighted
     - Delete icon per entry (confirm on click)

9. **Add JS session management**:
   - `currentSessionId = null` state variable
   - `loadSessions(projectId)` → `GET /api/sessions?project_id=X` → render sidebar list
   - `selectSession(sessionId)` → `GET /api/sessions/{id}` → render messages in chat area, set `currentSessionId`
   - `newChat()` → `POST /api/sessions`, clear messages, update sidebar, set `currentSessionId`
   - On send: if `currentSessionId == null`, call `newChat()` first, then send message
   - `POST /api/chat` payload includes `session_id: currentSessionId`
   - On response: if `title_updated` is true, refresh sidebar entry title
   - `deleteSession(sessionId)` → `DELETE /api/sessions/{id}` → remove from sidebar, clear chat if active

10. **Wire `loadSessions()`** to existing project selector — refresh sidebar on project change

---

## Files Changed

| File | Change |
|---|---|
| `app/memory/sessions.py` | **NEW** — SQLiteSessionStore |
| `app/core/config.py` | Add `SESSIONS_DB_PATH` setting |
| `main.py` | Add startup `init_db()` call |
| `app/api/routes.py` | New session endpoints + extend `/api/chat` |
| `app/agent/prompts.py` | Add `TITLE_PROMPT` |
| `static/index.html` | Sidebar layout + session JS logic |

---

## Verification Checklist

- [ ] Start app → `sessions.db` created, no errors
- [ ] `POST /api/sessions` → returns `session_id`
- [ ] `POST /api/chat` with `session_id` → response includes auto-generated title
- [ ] `GET /api/sessions?project_id=X` → lists sessions with titles
- [ ] Browser: "New Chat" button creates new entry in sidebar
- [ ] Browser: send first message → title appears in sidebar after response
- [ ] Browser: click old session → historical messages load in chat area
- [ ] Browser: delete session → removed from sidebar, chat cleared
- [ ] Browser: switch project → sidebar reloads with that project's sessions

---

## Decisions

- **SQLite + `aiosqlite`**: lightweight, async-compatible, no new infrastructure; separate from ChromaDB (which handles semantic vector search)
- **Title generated once** after the first exchange only — no repeated LLM calls per message
- **Session auto-created on first send** if no session is active — no friction to start chatting
- **Sessions scoped to `project_id`**: sidebar reloads when user switches projects
- Out of scope: message editing, inline sidebar rename (only via `PUT /api/sessions/{id}/title`), multi-user auth
