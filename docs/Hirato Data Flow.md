# Data Flow — Hirato LLM Project Secretary

## Overview

Hirato is a FastAPI application backed by a LangGraph agent. It gives each channel a persistent vector memory (ChromaDB) and can handle mixed messages that contain both a progress report **and** a question in a single input. All LLM inference is handled by an OpenAI-compatible LLM server. Chat history is persisted in a local SQLite database (`sessions.db`), surfaced through a left sidebar in the frontend.

---

## System Components

| Component | Role |
|---|---|
| **FastAPI** (`main.py`) | HTTP server; serves REST API + static frontend; initialises SQLite on startup |
| **API Routes** (`app/api/routes.py`) | Request parsing, validation, session management, response shaping |
| **LangGraph Agent** (`app/agent/graph.py`) | Stateful graph orchestrating all node transitions |
| **Agent Nodes** (`app/agent/nodes.py`) | Individual processing steps (router, extractor, store, retriever, answer) |
| **ChromaStore** (`app/memory/store.py`) | Persistent vector memory backed by ChromaDB |
| **SQLiteSessionStore** (`app/memory/sessions.py`) | Persistent chat sessions and message history backed by SQLite + aiosqlite |
| **OpenAI-compatible LLM** (external) | LLM inference for routing, extraction, answering, title generation, and embedding |

---

## API Endpoints

```
GET  /api/projects                         → list all project collections
POST /api/projects                         → create a new project (ChromaDB collection)
POST /api/chat                             → send a message; invokes the agent graph
POST /api/projects/{project_id}/import     → bulk-import pre-embedded JSON chunks
DELETE /api/projects/{project_id}          → delete project and all its memories

GET  /api/sessions?project_id=X            → list sessions for a project (ordered newest first)
POST /api/sessions                         → create a new session; body: {project_id}
GET  /api/sessions/{session_id}            → session metadata + full messages[]
DELETE /api/sessions/{session_id}          → delete session and all its messages
PUT  /api/sessions/{session_id}/title      → manually rename a session; body: {title}

GET  /                                     → static frontend (index.html)
```

---

## Session Flow

```
Browser
  │
  │  User selects project → GET /api/sessions?project_id=X
  │                       ← list of sessions rendered in sidebar
  │
  │  "New Chat" click → POST /api/sessions {project_id}
  │                   ← {id, project_id, title: null, created_at, updated_at}
  │                       new entry appears at top of sidebar
  │
  │  Send message (session active) → POST /api/chat {message, project_id, session_id}
  │                                ← {response, session_id, title_updated}
  │
  │  Click sidebar entry → GET /api/sessions/{id}
  │                      ← {…, messages: [{role, content, timestamp}, …]}
  │                          messages rendered in chat area
  │
  │  Delete entry → DELETE /api/sessions/{id}
  │               ← 204; entry removed from sidebar, chat cleared if active
```

---

## Chat Data Flow (`POST /api/chat`)

### 1. Request Ingestion

```
Client
  │
  │  POST /api/chat
  │  { "message": "...", "project_id": "my_project", "session_id": "uuid|null" }
  ▼
FastAPI → ChatRequest (Pydantic validation)
  │
  │  if session_id is null → create new session in SQLite
  │
  │  Load prior messages from sessions.messages (role="user") for context
  │
  │  initial AgentState:
  │  { messages: [...prior_user_messages, current_message], channel_id,
  │    decision: "answer_question", report_segment: None, question_segment: None,
  │    extracted_summary: None, retrieved_docs: None,
  │    store_response: None, answer_response: None, response: None }
  ▼
secretary_graph.ainvoke(initial_state)
```

### 2. Agent Graph — Routing Entry

```
START
  │
  ▼
router_node
  ├── Invokes: chat_llm (main LLM model)
  ├── Prompt: SPLITTER_PROMPT — classify AND segment the message, determine decision
  ├── Parses JSON response; sets decision to "save_memory" or "answer_question"
  ├── Writes: state["decision"]        = "save_memory" | "answer_question"
              state["report_segment"]  = report text | None
              state["question_segment"] = question text | None
  │
  ▼  (conditional routing based on decision)
route_decision(state)
  ├── if decision == "save_memory" → "extractor_node"
  └── else → "retriever_node"
```

### 3a. Save Memory Pipeline (`decision == "save_memory"`)

```
extractor_node
  ├── Invokes: chat_llm (main LLM model, optional think mode)
  ├── Prompt: EXTRACTOR_PROMPT
  ├── Input:  state["report_segment"]  (isolated report text)
  └── Writes: state["extracted_summary"]
              JSON: { week, accomplishments[], blockers[], next_steps[] }
  │
  ▼
store_node
  ├── Calls: chroma_store.add_memory() × 2
  │          ┌─ document: report_segment,       metadata: { date, type: "raw" }
  │          └─ document: extracted_summary,    metadata: { date, type: "summary" }
  └── Writes: state["store_response"] = "Your progress report has been saved successfully."
              state["response"] = state["store_response"]
  │
  ▼
END
```

### 3b. Answer Question Pipeline (`decision == "answer_question"`)

```
retriever_node
  ├── Calls: chroma_store.search_memory(channel_id, query, n_results=5)
  │          ├── query = state["question_segment"]  (isolated question text)
  │          ├── OpenAI-compatible embeddings.embed_documents([query])  (embedding model)
  │          ├── ChromaDB collection.query() — cosine similarity HNSW index
  │          └── Results sorted by metadata["date"] descending (newest first)
  └── Writes: state["retrieved_docs"]
              list of { content, metadata: { date, type }, distance }
  │
  ▼
answer_node
  ├── Formats context: "[N] (date, type)\n<content>" joined by "---"
  ├── Invokes: chat_llm with ANSWER_PROMPT.format(context=...) as system message
  │            HumanMessage = state["question_segment"]
  └── Writes: state["answer_response"] = LLM-generated answer string
              state["response"] = state["answer_response"]
  │
  ▼
END
```

### 4. Post-agent: Persistence & Title Generation

```
  ▼
sessions_store.add_message(session_id, "user",      message)
sessions_store.add_message(session_id, "assistant", agent_response)
  │
  │  if this is the first exchange (no prior messages):
  │      chat_llm.invoke([SystemMessage(TITLE_PROMPT), HumanMessage(message)])
  │      sessions_store.update_title(session_id, generated_title)
  │      title_updated = True
  │
  ▼
ChatResponse(response=..., session_id=..., title_updated=...)
```

---

## Import Data Flow (`POST /api/projects/{project_id}/import`)

```
Client
  │  multipart/form-data — .json file
  ▼
FastAPI → parse & validate JSON
  │  required shape: { "chunks": [ { chunk_id, chunk_text_embedded, ... }, ... ] }
  ▼
chroma_store.import_chunks(project_id, chunks)
  ├── get_or_create_collection(project_id)
  ├── Fetch existing IDs to detect duplicates
  └── Upsert new chunks:
       document: chunk["chunk_text_embedded"]
       metadata: { date: "1970-01-01", type: "reference_doc", source, section }
  │
  ▼
{ imported: N, skipped: M }
```

---

## Memory Layer (ChromaDB)

```
ChromaDB (persistent, ./chroma_db)
  │
  └── One Collection per channel_id
        ├── Embedding function: Custom embedding function (cosine HNSW)
        └── Document types stored:
             ┌────────────────┬─────────────────────────────────────────────┐
             │ type           │ content                                     │
             ├────────────────┼─────────────────────────────────────────────┤
             │ raw            │ original user progress report message       │
             │ summary        │ extracted JSON (week/accomplishments/etc.)  │
             │ reference_doc  │ imported external knowledge chunk           │
             └────────────────┴─────────────────────────────────────────────┘
```

---

## Chat History Layer (SQLite)

```
SQLite (./sessions.db)
  │
  ├── sessions
  │     id TEXT PK, project_id TEXT, title TEXT,
  │     created_at TEXT, updated_at TEXT
  │     (index: project_id, updated_at DESC)
  │
  └── messages
        id TEXT PK, session_id TEXT FK → sessions(id) ON DELETE CASCADE,
        role TEXT ("user"|"assistant"), content TEXT, timestamp TEXT
        (index: session_id, timestamp ASC)
```

---

## LLM Layer (OpenAI-compatible)

| Client | Config key | Purpose |
|---|---|---|
| `chat_llm` | `CHAT_MODEL` | Splitting/classification, extraction, answering, title generation — main model |
| `EmbeddingInference` | `EMBEDDING_MODEL` | Vectorises text for ChromaDB indexing and querying |

---

## AgentState Schema

```python
from typing import Any, Optional
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: list[str]
    channel_id: str
    decision: str  # "save_memory" or "answer_question"
    report_segment: Optional[str]
    question_segment: Optional[str]
    extracted_summary: Optional[str]
    retrieved_docs: Optional[list[dict[str, Any]]]
    store_response: Optional[str]
    answer_response: Optional[str]
    response: Optional[str]
```

---

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `CHAT_MODEL` | — | Main LLM model name |
| `CHAT_BASE_URL` | — | Main LLM base URL |
| `CHAT_API_KEY` | — | Main LLM API key |
| `CHAT_MODEL_ROUTER` | — | Router LLM model name |
| `ROUTER_BASE_URL` | — | Router LLM base URL |
| `ROUTER_API_KEY` | — | Router LLM API key |
| `CHAT_MODEL_THINK` | `false` | Enable think mode on main model |
| `EMBEDDING_MODEL` | — | Embedding model name |
| `EMBEDDING_BASE_URL` | — | Embedding base URL |
| `EMBEDDING_API_KEY` | — | Embedding API key |
| `CHROMA_PERSIST_PATH` | `./chroma_db` | ChromaDB storage path |
| `SESSIONS_DB_PATH` | `./sessions.db` | SQLite sessions database path |
| `PORT` | `7950` | HTTP server port |

---

## End-to-End Flow Diagram

```
Client (Browser / API consumer)
      │
      │ HTTP
      ▼
┌─────────────────────────────────────────────────────┐
│  FastAPI  (main.py)                                 │
│  ┌──────────────────────────────────────────────┐   │
│  │  /api/chat  →  routes.py  →  ChatRequest     │   │
│  └──────────────────────┬───────────────────────┘   │
└─────────────────────────┼───────────────────────────┘
                          │ ainvoke(AgentState)
                          ▼
┌─────────────────────────────────────────────────────┐
│  LangGraph  (graph.py)   — conditional routing      │
│                                                     │
│  START → router_node                                │
│            │  classifies & segments message         │
│            │  sets decision: "save_memory" |        │
│            │           "answer_question"            │
│            ▼                                        │
│      route_decision(state)                          │
│         │                                           │
│         ├─ if "save_memory" → extractor_node        │
│         │              ▼                              │
│         │          store_node → END                 │
│         │                                           │
│         └─ else ("answer_question") → retriever_node│
│                              ▼                        │
│                          answer_node → END          │
└──────────┬──────────────────────────┬───────────────┘
           │ LLM calls                │ vector ops
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────────┐
│  OpenAI-compatible LLM  │      │  ChromaDB (./chroma_db)  │
│  - chat model    │      │  - per-channel collection│
│    (split+answer)│      │  - cosine HNSW index     │
│  - embed model   │      │  - raw / summary / ref   │
└──────────────────┘      └──────────────────────────┘
```
