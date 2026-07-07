# Data Flow — Hirato LLM Project Secretary

## Overview

Hirato is a FastAPI application backed by a LangGraph agent. It gives each project a persistent vector memory (ChromaDB) and routes user messages to one of two pipelines: **ingestion** (progress reports) or **retrieval** (questions). All LLM inference is handled by a self-hosted Ollama instance.

---

## System Components

| Component | Role |
|---|---|
| **FastAPI** (`main.py`) | HTTP server; serves REST API + static frontend |
| **API Routes** (`app/api/routes.py`) | Request parsing, validation, response shaping |
| **LangGraph Agent** (`app/agent/graph.py`) | Stateful graph orchestrating all node transitions |
| **Agent Nodes** (`app/agent/nodes.py`) | Individual processing steps (router, extractor, store, retriever, answer) |
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
  │  { messages: [message], project_id, intent: None,
  │    extracted_summary: None, retrieved_docs: None, response: None }
  ▼
secretary_graph.ainvoke(initial_state)
```

### 2. Agent Graph — Common Entry

```
START
  │
  ▼
router_node
  ├── Invokes: router_llm (lightweight Ollama model)
  ├── Prompt: ROUTER_PROMPT — classify as "progress_report" or "question"
  └── Writes: state["intent"] = "progress_report" | "question"
  │
  ▼
_route_intent()   ← conditional edge
  ├── "progress_report" ──► extractor_node
  └── "question"          ──► retriever_node
```

### 3a. Progress Report Pipeline

```
extractor_node
  ├── Invokes: chat_llm (main Ollama model, optional think mode)
  ├── Prompt: EXTRACTOR_PROMPT
  ├── Input:  state["messages"][-1]  (raw user text)
  └── Writes: state["extracted_summary"]
              JSON: { week, accomplishments[], blockers[], next_steps[] }
  │
  ▼
store_node
  ├── Calls: chroma_store.add_memory() × 2
  │          ┌─ document: raw user message,     metadata: { date, type: "raw" }
  │          └─ document: extracted_summary,    metadata: { date, type: "summary" }
  └── Writes: state["response"] = "Your progress report has been saved successfully."
  │
  ▼
END  →  ChatResponse(response=...)
```

### 3b. Question Pipeline

```
retriever_node
  ├── Calls: chroma_store.search_memory(project_id, query, n_results=5)
  │          ├── OllamaEmbeddings.embed_documents([query])  (embedding model)
  │          ├── ChromaDB collection.query() — cosine similarity HNSW index
  │          └── Results sorted by metadata["date"] descending (newest first)
  └── Writes: state["retrieved_docs"]
              list of { content, metadata: { date, type }, distance }
  │
  ▼
answer_node
  ├── Formats context: "[N] (date, type)\n<content>" joined by "---"
  ├── Invokes: chat_llm with ANSWER_PROMPT.format(context=...) as system message
  └── Writes: state["response"] = LLM-generated answer string
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
| `router_llm` | `CHAT_MODEL_ROUTER` | Intent classification — fast, lightweight |
| `chat_llm` | `CHAT_MODEL` | Extraction + answering — main model (optional think mode via `CHAT_MODEL_THINK`) |
| `OllamaEmbeddings` | `EMBEDDING_MODEL` | Vectorises text for ChromaDB indexing and querying |

All three clients connect to `OLLAMA_CHAT_URL` with a bearer token (`OLLAMA_BEARER`).

---

## AgentState Schema

```python
class AgentState(TypedDict):
    messages:          list[str]               # conversation turns
    project_id:        str                     # scopes all memory operations
    intent:            Optional[str]           # "progress_report" | "question"
    extracted_summary: Optional[str]           # JSON string from extractor_node
    retrieved_docs:    Optional[list[dict]]    # [{content, metadata, distance}, ...]
    response:          Optional[str]           # final answer returned to client
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
│  LangGraph  (graph.py)                              │
│                                                     │
│  START → router_node ──┬── "progress_report"        │
│                        │     extractor_node          │
│                        │     store_node → END        │
│                        │                             │
│                        └── "question"               │
│                              retriever_node          │
│                              answer_node → END       │
└──────────┬──────────────────────────┬───────────────┘
           │ LLM calls                │ vector ops
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────────┐
│  Ollama          │      │  ChromaDB (./chroma_db)  │
│  - router model  │      │  - per-project collection│
│  - chat model    │      │  - cosine HNSW index     │
│  - embed model   │      │  - raw / summary / ref   │
└──────────────────┘      └──────────────────────────┘
```
