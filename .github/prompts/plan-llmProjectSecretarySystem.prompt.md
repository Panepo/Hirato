# Plan: LLM Project Secretary System

## TL;DR
Build a multi-project AI secretary using FastAPI + LangGraph + ChromaDB + Ollama. User types weekly progress reports; the agent extracts, embeds, and stores them in ChromaDB (per-project). When the user asks questions, the agent semantically retrieves relevant memories and answers via the local Ollama LLM.

---

## Stack
- **LLM (extractor + answer)**: Ollama @ `http://10.168.3.58`, model `qwen3.6:35b`, bearer auth
- **LLM (router)**: `nemotron-3-nano:4b` — fast binary classification only
- **Embeddings**: Ollama `embeddinggemma:300m` via `OllamaEmbeddings`
- **Orchestration**: LangGraph `StateGraph`
- **Memory**: ChromaDB (local persistent, collection-per-project)
- **API**: FastAPI
- **UI**: Single-page HTML/JS chat (served by FastAPI static files)

---

## Project Structure
```
d:\Github\Hirato\
├── main.py
├── requirements.txt          # add: chromadb, python-dotenv
├── .env                      # already exists
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   └── prompts.py
│   ├── memory/
│   │   ├── __init__.py
│   │   └── store.py
│   └── core/
│       ├── __init__.py
│       └── config.py
├── static/
│   └── index.html
├── chroma_db/                # auto-created by ChromaDB
└── .github/
    └── reference/            # pre-embedded JSON files (*.embedded.json)
```

---

## Phase 1: Foundation

### Step 1 — Update requirements.txt
Add: `chromadb`, `python-dotenv`

### Step 2 — app/core/config.py
Load `.env` values:
- `OLLAMA_CHAT_URL`, `OLLAMA_BEARER`, `CHAT_MODEL`, `CHAT_MODEL_ROUTER`, `CHAT_MODEL_THINK`, `EMBEDDING_MODEL`
- `CHROMA_PERSIST_PATH = "./chroma_db"`

### Step 3 — app/memory/store.py
ChromaDB client wrapper:
- `ChromaStore` class with persistent client at `CHROMA_PERSIST_PATH`
- `get_or_create_collection(project_id)` — one collection per project
- `add_memory(project_id, content, metadata)` — upsert doc with embedding; `metadata` **must** include `date` (ISO `YYYY-MM-DD`) and `type` (`"raw"` or `"summary"`)
- `search_memory(project_id, query, n_results=5)` → list of relevant docs, **sorted by `metadata["date"]` descending** before returning
- `list_projects()` → list all collection names (= project IDs)
- `import_chunks(project_id, chunks)` — bulk upsert from pre-embedded JSON; uses `chunk_id` as ChromaDB doc ID (idempotent); sets `metadata.type = "reference_doc"` and `metadata.date = "1970-01-01"` so reference material always sorts below dated progress entries

### Step 4 — app/agent/prompts.py
Define system prompts:
- `ROUTER_PROMPT` — classify user message as `"progress_report"` or `"question"`
- `EXTRACTOR_PROMPT` — extract structured summary from weekly report (week, accomplishments, blockers, next_steps)
- `ANSWER_PROMPT` — answer user question given retrieved context docs; must include the instruction: **"Documents are ordered newest-first. If facts conflict across entries, trust the most recent date."`**

---

## Phase 2: LangGraph Agent

### Step 5 — app/agent/nodes.py
Five node functions, each takes `AgentState` and returns updated state:

1. **`router_node`** — LLM call with ROUTER_PROMPT; sets `state["intent"]`
2. **`extractor_node`** — LLM call with EXTRACTOR_PROMPT on the user message; sets `state["extracted_summary"]`
3. **`store_node`** — calls `ChromaStore.add_memory()` twice: raw text + extracted summary; both with mandatory `date=today` in metadata; sets `state["response"]` = confirmation message
4. **`retriever_node`** — calls `ChromaStore.search_memory()`; results are already date-sorted (newest-first) by the store; sets `state["retrieved_docs"]`
5. **`answer_node`** — LLM call with ANSWER_PROMPT + retrieved_docs as context; sets `state["response"]`

### Step 6 — app/agent/graph.py
`AgentState` TypedDict: `messages`, `project_id`, `intent`, `extracted_summary`, `retrieved_docs`, `response`

Build `StateGraph`:
```
START → router_node
router_node → [conditional edge]
  "progress_report" → extractor_node → store_node → END
  "question"        → retriever_node → answer_node → END
```
Compile with `graph.compile()` → exported as `secretary_graph`

### Step 7 — Ollama client setup (in config.py or nodes.py)
Instantiate two separate `ChatOllama` clients from `langchain_ollama`:
```python
# Heavy model — extractor_node + answer_node
chat_llm = ChatOllama(
    base_url=settings.OLLAMA_CHAT_URL,
    model=settings.CHAT_MODEL,          # qwen3.6:35b
    client_kwargs={"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}}
)

# Fast model — router_node only
router_llm = ChatOllama(
    base_url=settings.OLLAMA_CHAT_URL,
    model=settings.CHAT_MODEL_ROUTER,   # nemotron-3-nano:4b
    client_kwargs={"headers": {"Authorization": f"Bearer {settings.OLLAMA_BEARER}"}}
)
```
Use `OllamaEmbeddings` similarly for the embedding model.

---

## Phase 3: API & UI

### Step 8 — app/api/routes.py
Endpoints:
- `GET  /api/projects` — list projects from ChromaDB collections
- `POST /api/projects` — create new project `{name: str, description: str}`
- `POST /api/chat` — body: `{message: str, project_id: str}` → invoke `secretary_graph`, return `{response: str}`
- `POST /api/projects/{project_id}/import` — multipart upload of a `.embedded.json` file; validates schema (must have top-level `chunks` array, each with `chunk_id` and `chunk_text_embedded`); calls `ChromaStore.import_chunks()`; returns `{imported: int, skipped: int}`

### Step 9 — main.py
FastAPI app: mount `static/` dir, include routes from `app/api/routes.py`, CORS middleware

### Step 10 — static/index.html
Single-page UI:
- Top bar: project dropdown (GET /api/projects) + "New Project" button + "Import JSON" button
- Chat area: message bubbles (user right, secretary left)
- Input bar: textarea + Send button
- "Import JSON" button opens a file picker (`.json` only); POSTs the file to `POST /api/projects/{project_id}/import`; shows toast with imported/skipped counts
- JS: fetch POST /api/chat, append messages to chat area
- Basic CSS styling (clean, minimal)

---

## Verification
1. `uvicorn main:app --reload` starts without errors
2. Create a project via the UI → appears in dropdown
3. Type a weekly report like "This week I finished the login module, blocked by DB migration" → secretary confirms it was saved
4. Ask "What was I blocked by last week?" → secretary retrieves and answers correctly
5. Switch project → asking the same question returns no info (isolation check)
6. Check ChromaDB persistence: restart server, ask the same question → answer still works
7. Import `Getac S510AD FAQ_v01.embedded.json` into a project → UI shows imported count
8. Ask "What are the product highlights of S510AD?" → secretary answers from imported FAQ chunks
9. Re-import the same file → imported=0, skipped=N (idempotency check)
10. Add a weekly report after importing → ask a question; secretary answers from both sources, preferring the dated report over the reference doc when facts conflict

---

## Decisions
- **One ChromaDB collection per project** — clean isolation, easy to list projects
- **Store both raw + extracted summary** — raw for context richness, summary for clean retrieval
- **Temporal consistency via date metadata + recency sort** — every stored doc carries an ISO `date`; `search_memory` sorts results newest-first; `ANSWER_PROMPT` instructs the LLM to trust the most recent entry when facts conflict. This ensures `A → b` (this week) wins over `A → a` (last week) without any graph or upsert complexity.
- **Pre-embedded JSON import (bypass re-embedding)** — the `.embedded.json` format stores `chunk_text_embedded` (pre-formatted text with document/section context) and `chunk_id`. `import_chunks` uses `chunk_text_embedded` as the document and `chunk_id` as the ChromaDB ID. ChromaDB re-embeds via `OllamaEmbeddings` on upsert; the `embedded` suffix in the filename refers to the text formatting, not pre-computed vectors — so the same embedding model is used for consistency with progress reports.
- **Reference docs rank below progress reports** — imported chunks receive `date = "1970-01-01"`; `search_memory` sorts newest-first, so weekly reports (current year dates) always surface above static reference material. The `ANSWER_PROMPT` "trust newest" rule reinforces this.
- **Import is idempotent** — using `chunk_id` as the ChromaDB document ID means re-uploading the same file upserts without duplication.
- **No auth/login on the web UI** — out of scope for now
- **Conversation history**: single-turn per API call (no multi-turn memory in LangGraph state for now); can be added later
- **No streaming** for now (simpler); can add SSE streaming later

## Further Considerations
1. **Ollama bearer token in `client_kwargs`**: `langchain_ollama.ChatOllama` passes `client_kwargs` to the underlying `httpx` client — needs verification at runtime; fallback is a custom `BaseChatModel` wrapping `requests`.
2. **`CHAT_MODEL_THINK=true`**: Applied to `chat_llm` (qwen3.6:35b) only — thinking mode is valuable on the 35B model. The router LLM (`nemotron-3-nano:4b`) should NOT use thinking mode to keep latency low.
3. **Dual-model rationale**: `router_node` fires on every message (simple binary classification — fast model is fine). `extractor_node` and `answer_node` require reliable structured output and context synthesis — the 35B model handles these.
