# Data Flow — Hirato LLM Project Secretary

## Overview

Hirato is a FastAPI application backed by a LangGraph agent. It gives each project a persistent vector memory (ChromaDB) and can handle mixed messages that contain both a progress report **and** a question in a single input. All LLM inference is handled by a self-hosted Ollama instance. Chat history is persisted in a local SQLite database (`sessions.db`), surfaced through a left sidebar in the frontend.

---

## System Components

| Component | Role |
|---|---|
| **FastAPI** (`main.py`) | HTTP server; serves REST API + static frontend; initialises SQLite on startup |
| **API Routes** (`app/api/routes.py`) | Request parsing, validation, session management, response shaping |
| **LangGraph Agent** (`app/agent/graph.py`) | Stateful graph orchestrating all node transitions |
| **Agent Nodes** (`app/agent/nodes.py`) | Individual processing steps (router/splitter, extractor, store, retriever, answer, combiner) |
| **ChromaStore** (`app/memory/store.py`) | Persistent vector memory backed by ChromaDB |
| **SQLiteSessionStore** (`app/memory/sessions.py`) | Persistent chat sessions and message history backed by SQLite + aiosqlite |
| **Ollama** (external) | LLM inference for routing, extraction, answering, title generation, and embedding |

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
  │  { messages: [...prior_user_messages, current_message], project_id,
  │    intents: [], report_segment: None, question_segment: None,
  │    extracted_summary: None, retrieved_docs: None,
  │    store_response: None, answer_response: None, response: None }
  ▼
secretary_graph.ainvoke(initial_state)
```

### 2. Agent Graph — Common Entry

```
START
  │
  ▼
router_node
  ├── Invokes: chat_llm (main Ollama model)
  ├── Prompt: SPLITTER_PROMPT — classify AND segment the message
  ├── Parses JSON response; reconciles intents against segments
  ├── Fallback on parse error: intents=["question"], question_segment=full message
  └── Writes: state["intents"]         = ["progress_report"] | ["question"] | both
              state["report_segment"]  = report text | None
              state["question_segment"] = question text | None
  │
  ▼  (always continues — all downstream nodes guard on intents)
extractor_node  →  store_node  →  retriever_node  →  answer_node  →  combiner_node
```

### 3a. Progress Report Pipeline

```
extractor_node
  ├── Guard: skips entirely if "progress_report" not in state["intents"]
  ├── Invokes: chat_llm (main Ollama model, optional think mode)
  ├── Prompt: EXTRACTOR_PROMPT
  ├── Input:  state["report_segment"]  (isolated report text)
  └── Writes: state["extracted_summary"]
              JSON: { week, accomplishments[], blockers[], next_steps[] }
  │
  ▼
store_node
  ├── Guard: skips entirely if "progress_report" not in state["intents"]
  ├── Calls: chroma_store.add_memory() × 2
  │          ┌─ document: report_segment,       metadata: { date, type: "raw" }
  │          └─ document: extracted_summary,    metadata: { date, type: "summary" }
  └── Writes: state["store_response"] = "Your progress report has been saved successfully."
```

### 3b. Question Pipeline

```
retriever_node
  ├── Guard: skips entirely if "question" not in state["intents"]
  ├── Calls: chroma_store.search_memory(project_id, query, n_results=5)
  │          ├── query = state["question_segment"]  (isolated question text)
  │          ├── OllamaEmbeddings.embed_documents([query])  (embedding model)
  │          ├── ChromaDB collection.query() — cosine similarity HNSW index
  │          └── Results sorted by metadata["date"] descending (newest first)
  └── Writes: state["retrieved_docs"]
              list of { content, metadata: { date, type }, distance }
  │
  ▼
answer_node
  ├── Guard: skips entirely if "question" not in state["intents"]
  ├── Formats context: "[N] (date, type)\n<content>" joined by "---"
  ├── Invokes: chat_llm with ANSWER_PROMPT.format(context=...) as system message
  │            HumanMessage = state["question_segment"]
  └── Writes: state["answer_response"] = LLM-generated answer string
```

### 3c. Combiner (always runs)

```
combiner_node
  ├── Collects state["store_response"]  (present if report pipeline ran)
  ├── Collects state["answer_response"] (present if question pipeline ran)
  └── Writes: state["response"] = store_response + "\n\n" + answer_response
              (only non-None parts joined; falls back to "No response generated.")
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
  └── One Collection per project_id
        ├── Embedding function: OllamaEmbeddings (cosine HNSW)
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

## LLM Layer (Ollama)

| Client | Config key | Purpose |
|---|---|---|
| `chat_llm` | `CHAT_MODEL` | Splitting/classification, extraction, answering, title generation — main model (optional think mode via `CHAT_MODEL_THINK`) |
| `OllamaEmbeddings` | `EMBEDDING_MODEL` | Vectorises text for ChromaDB indexing and querying |

All clients connect to `OLLAMA_CHAT_URL` with a bearer token (`OLLAMA_BEARER`).

---

## AgentState Schema

```python
class AgentState(TypedDict):
    messages:          list[str]               # conversation turns (prior user messages + current)
    project_id:        str                     # scopes all memory operations
    intents:           list[str]               # ["progress_report"] | ["question"] | both
    report_segment:    Optional[str]           # isolated report text (from router_node)
    question_segment:  Optional[str]           # isolated question text (from router_node)
    extracted_summary: Optional[str]           # JSON string from extractor_node
    retrieved_docs:    Optional[list[dict]]    # [{content, metadata, distance}, ...]
    store_response:    Optional[str]           # set by store_node if report pipeline ran
    answer_response:   Optional[str]           # set by answer_node if question pipeline ran
    response:          Optional[str]           # final combined response (from combiner_node)
```

---

## Configuration

| Key | Default | Purpose |
|---|---|---|
| `OLLAMA_CHAT_URL` | — | Ollama base URL |
| `OLLAMA_BEARER` | — | Bearer token for Ollama |
| `CHAT_MODEL` | — | Main LLM model name |
| `CHAT_MODEL_THINK` | `false` | Enable think mode on main model |
| `EMBEDDING_MODEL` | — | Embedding model name |
| `CHROMA_PERSIST_PATH` | `./chroma_db` | ChromaDB storage path |
| `SESSIONS_DB_PATH` | `./sessions.db` | SQLite sessions database path |
| `PORT` | `7950` | HTTP server port |

## Overview

Hirato is a FastAPI application backed by a LangGraph agent. It gives each project a persistent vector memory (ChromaDB) and can handle mixed messages that contain both a progress report **and** a question in a single input. All LLM inference is handled by a self-hosted Ollama instance.

---

## System Components

| Component | Role |
|---|---|
| **FastAPI** (`main.py`) | HTTP server; serves REST API + static frontend |
| **API Routes** (`app/api/routes.py`) | Request parsing, validation, response shaping |
| **LangGraph Agent** (`app/agent/graph.py`) | Stateful graph orchestrating all node transitions |
| **Agent Nodes** (`app/agent/nodes.py`) | Individual processing steps (router/splitter, extractor, store, retriever, answer, combiner) |
| **ChromaStore** (`app/memory/store.py`) | Persistent vector memory backed by ChromaDB |
| **Ollama** (external) | LLM inference for routing, extraction, answering, and embedding |

---

## API Endpoints

```
GET  /api/projects                        → list all project collections
POST /api/projects                        → create a new project (ChromaDB collection)
POST /api/chat                            → send a message; invokes the agent graph
POST /api/projects/{project_id}/import    → bulk-import pre-embedded JSON chunks
GET  /                                    → static frontend (index.html)
```

---

## Chat Data Flow (`POST /api/chat`)

### 1. Request Ingestion

```
Client
  │
  │  POST /api/chat
  │  { "message": "...", "project_id": "my_project" }
  ▼
FastAPI → ChatRequest (Pydantic validation)
  │
  │  initial AgentState:
  │  { messages: [message], project_id, intents: [],
  │    report_segment: None, question_segment: None,
  │    extracted_summary: None, retrieved_docs: None,
  │    store_response: None, answer_response: None, response: None }
  ▼
secretary_graph.ainvoke(initial_state)
```

### 2. Agent Graph — Common Entry

```
START
  │
  ▼
router_node
  ├── Invokes: chat_llm (main Ollama model)
  ├── Prompt: SPLITTER_PROMPT — classify AND segment the message
  ├── Parses JSON response; reconciles intents against segments
  ├── Fallback on parse error: intents=["question"], question_segment=full message
  └── Writes: state["intents"]         = ["progress_report"] | ["question"] | both
              state["report_segment"]  = report text | None
              state["question_segment"] = question text | None
  │
  ▼  (always continues — all downstream nodes guard on intents)
extractor_node  →  store_node  →  retriever_node  →  answer_node  →  combiner_node
```

### 3a. Progress Report Pipeline

```
extractor_node
  ├── Guard: skips entirely if "progress_report" not in state["intents"]
  ├── Invokes: chat_llm (main Ollama model, optional think mode)
  ├── Prompt: EXTRACTOR_PROMPT
  ├── Input:  state["report_segment"]  (isolated report text)
  └── Writes: state["extracted_summary"]
              JSON: { week, accomplishments[], blockers[], next_steps[] }
  │
  ▼
store_node
  ├── Guard: skips entirely if "progress_report" not in state["intents"]
  ├── Calls: chroma_store.add_memory() × 2
  │          ┌─ document: report_segment,       metadata: { date, type: "raw" }
  │          └─ document: extracted_summary,    metadata: { date, type: "summary" }
  └── Writes: state["store_response"] = "Your progress report has been saved successfully."
```

### 3b. Question Pipeline

```
retriever_node
  ├── Guard: skips entirely if "question" not in state["intents"]
  ├── Calls: chroma_store.search_memory(project_id, query, n_results=5)
  │          ├── query = state["question_segment"]  (isolated question text)
  │          ├── OllamaEmbeddings.embed_documents([query])  (embedding model)
  │          ├── ChromaDB collection.query() — cosine similarity HNSW index
  │          └── Results sorted by metadata["date"] descending (newest first)
  └── Writes: state["retrieved_docs"]
              list of { content, metadata: { date, type }, distance }
  │
  ▼
answer_node
  ├── Guard: skips entirely if "question" not in state["intents"]
  ├── Formats context: "[N] (date, type)\n<content>" joined by "---"
  ├── Invokes: chat_llm with ANSWER_PROMPT.format(context=...) as system message
  │            HumanMessage = state["question_segment"]
  └── Writes: state["answer_response"] = LLM-generated answer string
```

### 3c. Combiner (always runs)

```
combiner_node
  ├── Collects state["store_response"]  (present if report pipeline ran)
  ├── Collects state["answer_response"] (present if question pipeline ran)
  └── Writes: state["response"] = store_response + "\n\n" + answer_response
              (only non-None parts joined; falls back to "No response generated.")
  │
  ▼
END  →  ChatResponse(response=...)
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
  └── One Collection per project_id
        ├── Embedding function: OllamaEmbeddings (cosine HNSW)
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

## LLM Layer (Ollama)

| Client | Config key | Purpose |
|---|---|---|
| `chat_llm` | `CHAT_MODEL` | Splitting/classification, extraction, and answering — main model (optional think mode via `CHAT_MODEL_THINK`) |
| `OllamaEmbeddings` | `EMBEDDING_MODEL` | Vectorises text for ChromaDB indexing and querying |

All clients connect to `OLLAMA_CHAT_URL` with a bearer token (`OLLAMA_BEARER`).

> **Note:** `router_llm` / `CHAT_MODEL_ROUTER` have been removed. The main `chat_llm` now handles both segmentation and all downstream LLM tasks, ensuring the model capable of precise boundary detection is always used for splitting.

---

## AgentState Schema

```python
class AgentState(TypedDict):
    messages:          list[str]               # conversation turns
    project_id:        str                     # scopes all memory operations
    intents:           list[str]               # ["progress_report"] | ["question"] | both
    report_segment:    Optional[str]           # isolated report text (from router_node)
    question_segment:  Optional[str]           # isolated question text (from router_node)
    extracted_summary: Optional[str]           # JSON string from extractor_node
    retrieved_docs:    Optional[list[dict]]    # [{content, metadata, distance}, ...]
    store_response:    Optional[str]           # set by store_node if report pipeline ran
    answer_response:   Optional[str]           # set by answer_node if question pipeline ran
    response:          Optional[str]           # final combined response (from combiner_node)
```

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
│  LangGraph  (graph.py)   — linear pipeline          │
│                                                     │
│  START → router_node                                │
│            │  splits message into segments          │
│            ▼                                        │
│          extractor_node  (skips if no report)       │
│            ▼                                        │
│          store_node      (skips if no report)       │
│            ▼                                        │
│          retriever_node  (skips if no question)     │
│            ▼                                        │
│          answer_node     (skips if no question)     │
│            ▼                                        │
│          combiner_node  → END                       │
└──────────┬──────────────────────────┬───────────────┘
           │ LLM calls                │ vector ops
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────────┐
│  Ollama          │      │  ChromaDB (./chroma_db)  │
│  - chat model    │      │  - per-project collection│
│    (split+answer)│      │  - cosine HNSW index     │
│  - embed model   │      │  - raw / summary / ref   │
└──────────────────┘      └──────────────────────────┘
```
