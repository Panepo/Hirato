# Hirato — LLM Project Secretary

An AI-powered project secretary that lets teams log progress reports and query project history through a chat interface. Built with FastAPI, LangGraph, ChromaDB, and Ollama.

## Features

- **Multi-project management** — create isolated project workspaces, each with their own memory
- **Progress report ingestion** — paste daily/weekly updates; the agent extracts structured summaries (accomplishments, blockers, next steps) and stores them as searchable memories
- **Semantic Q&A** — ask questions about a project and get answers grounded in stored memories, ordered newest-first
- **JSON import** — bulk-import pre-embedded documents via file upload
- **Browser UI** — single-page chat interface served directly from the app

## Architecture

```
User message
     │
     ▼
 router_node          ← classifies intent
     │
     ├─ progress_report ─► extractor_node ─► store_node ─► ChromaDB
     │
     └─ question        ─► retriever_node ─► answer_node ─► response
```

The LangGraph agent runs two paths:
- **Report path**: LLM extracts a JSON summary → both raw text and summary are upserted into ChromaDB
- **Question path**: ChromaDB semantic search retrieves the top-5 relevant memories → LLM generates an answer from context

## Tech Stack

| Layer | Technology |
|---|---|
| API & server | FastAPI + Uvicorn |
| Agent orchestration | LangGraph |
| LLM inference | Ollama (chat + router models) |
| Embeddings | Ollama embeddings |
| Vector store | ChromaDB (persistent, local) |
| Frontend | Vanilla HTML/CSS/JS (served as static files) |

## Requirements

- Python ≥ 3.11
- A running [Ollama](https://ollama.com) instance with your chosen models pulled

## Installation

```bash
git clone https://github.com/your-username/hirato.git
cd hirato
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```env
OLLAMA_CHAT_URL=http://localhost:11434
OLLAMA_BEARER=                    # leave empty if no auth
CHAT_MODEL=llama3.2               # model used for extraction and answering
CHAT_MODEL_ROUTER=llama3.2        # model used for intent classification (can be smaller)
CHAT_MODEL_THINK=false            # set true to enable thinking mode (if model supports it)
EMBEDDING_MODEL=nomic-embed-text  # embedding model
CHROMA_PERSIST_PATH=./chroma_db   # local path for ChromaDB storage
PORT=7950
```

## Running

**With [Poe the Poet](https://poethepoet.natn.io/):**
```bash
pip install poethepoet
poe dev
```

**With Uvicorn directly:**
```bash
uvicorn main:app --port 7950 --reload
```

Then open [http://localhost:7950](http://localhost:7950) in your browser.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create a new project |
| `POST` | `/api/chat` | Send a message (report or question) |
| `POST` | `/api/projects/{project_id}/import` | Bulk-import a JSON file |

## Project Structure

```
├── main.py                  # FastAPI app entry point
├── requirements.txt
├── pyproject.toml
├── app/
│   ├── agent/
│   │   ├── graph.py         # LangGraph state machine definition
│   │   ├── nodes.py         # Agent node functions (router, extractor, store, retriever, answer)
│   │   └── prompts.py       # System prompts
│   ├── api/
│   │   └── routes.py        # REST endpoints
│   ├── core/
│   │   └── config.py        # Pydantic settings (loaded from .env)
│   └── memory/
│       └── store.py         # ChromaDB wrapper
├── static/
│   └── index.html           # Single-page web UI
└── chroma_db/               # Persistent vector store (auto-created)
```
