# Hirato — LLM Project Secretary

An AI-powered project secretary that lets teams log progress reports and query project history through chat interfaces (web and Telegram). Built with FastAPI, LangGraph, LanceDB, OpenAI-compatible LLMs, and Vue 3.

## Features

- **Multi-project management** — create isolated project workspaces, each with their own memory
- **Progress report ingestion** — paste daily/weekly updates; the agent extracts structured summaries (accomplishments, blockers, next steps) and stores them as searchable memories
- **Semantic Q&A** — ask questions about a project and get answers grounded in stored memories, ordered newest-first
- **JSON import** — bulk-import pre-embedded documents via file upload
- **Authentication** — JWT-based authentication integrated with Shiratsuyu user system
- **Multi-channel interface** — browser UI and Telegram bot support
- **Role-based access control** — channel-level admin permissions via user groups

## Architecture

```
User message
     │
     ▼
 router_node          ← classifies intent
     │
     ├─ progress_report ─► extractor_node ─► store_node ─► LanceDB
     │
     └─ question        ─► retriever_node ─► answer_node ─► response
```

The LangGraph agent runs two paths:
- **Report path**: LLM extracts a JSON summary → both raw text and summary are upserted into LanceDB
- **Question path**: LanceDB semantic search retrieves the top-5 relevant memories → LLM generates an answer from context

## Tech Stack

| Layer | Technology |
|---|---|
| API & server | FastAPI + Uvicorn |
| Agent orchestration | LangGraph |
| LLM inference | OpenAI-compatible LLMs |
| Embeddings | OpenAI-compatible embeddings |
| Vector store | LanceDB (persistent, local, embedded) |
| Frontend | Vue 3 + TypeScript + Vite + Pinia + Vue Router |
| Authentication | JWT + Shiratsuyu integration |
| Bot | Python-telegram-bot |

## Requirements

- Python ≥ 3.11
- Node.js ≥ 18 (for frontend build)
- An OpenAI-compatible LLM server with your chosen models available

## Installation

**Backend:**
```bash
git clone https://github.com/your-username/hirato.git
cd hirato
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
npm run build
```

The built frontend will be placed in `dist/` and copied to `static/` for serving.

## Configuration

Create a `.env` file in the project root:

```env
PORT=7950

# LLM
CHAT_MODEL=''
CHAT_BASE_URL=''
CHAT_API_KEY=''

# Router
CHAT_MODEL_ROUTER=''
ROUTER_BASE_URL=''
ROUTER_API_KEY=''

# Embedding
EMBEDDING_MODEL=''
EMBEDDING_BASE_URL=''
EMBEDDING_API_KEY=''

LANCEDB_PERSIST_PATH=./lancedb_db   # local path for LanceDB storage
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

VISION_CHAT_MODEL=''
VISION_CHAT_BASE_URL=''
VISION_CHAT_API_KEY=''

# Reranker (optional)
RERANKING_MODEL=''
RERANKING_BASE_URL=''
RERANKING_API_KEY=''

# Vision (optional)
INDEXER_BASE_URL=''
INDEXER_API_KEY=''

# Database paths
SESSIONS_DB_PATH=./sessions.db      # session history storage
AUTH_DB_PATH=./auth.db              # authentication database

# Telegram Bot (optional)
TELEGRAM_BOT_TOKEN=''
TELEGRAM_ACCESS_CODE=''

# Authentication (Shiratsuyu integration)
SHIRATSUYU_BASE_URL=''
SHIRATSUYU_SERVER_NAME=hirato
JWT_SECRET=''
JWT_ALGORITHM=HS256
SITE_ADMIN_ROLE_ID=52
```

## Running

**Development mode:**

1. Start the backend:
```bash
uvicorn main:app --port 7950 --reload
```

2. In a separate terminal, start the frontend dev server:
```bash
cd frontend
npm run dev
```

3. Open [http://localhost:5173](http://localhost:5173) in your browser (frontend will proxy to backend API).

**Production mode:**

1. Build the frontend:
```bash
cd frontend
npm run build
```

2. Copy built files to static directory:
```bash
copy frontend\dist\* static\
# On Linux/Mac:
# cp -r frontend/dist/* static/
```

3. Start the server:
```bash
uvicorn main:app --port 7950
```

4. Open [http://localhost:7950](http://localhost:7950) in your browser.

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

### Authentication
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Login with email/password |
| `GET` | `/api/auth/me` | Get current user info (requires auth) |

### Projects & Chat
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create a new project |
| `POST` | `/api/chat` | Send a message (report or question) |
| `POST` | `/api/projects/{project_id}/import` | Bulk-import a JSON file |

## Project Structure
├── app/
│   ├── agent/
│   │   ├── graph.py         # LangGraph state machine definition
│   │   ├── nodes.py         # Agent node functions (router, extractor, store, retriever, answer)
│   │   ├── node_async.py    # Async node implementations
│   │   ├── node_config.py   # Node configuration
│   │   ├── prompts.py       # System prompts
│   │   └── extractor_utils.py & retriever_utils.py
│   ├── api/
│   │   ├── auth_routes.py   # Authentication endpoints
│   │   └── routes.py        # REST endpoints for projects/chat
│   ├── bot/
│   │   ├── bot.py           # Telegram bot setup
│   │   ├── handlers.py      # Telegram message handlers
│   │   ├── auth.py          # Telegram authentication
│   │   └── telegram_sessions.py
│   ├── core/
│   │   ├── config.py        # Pydantic settings (loaded from .env)
│   │   ├── auth.py          # JWT authentication & user validation
│   │   ├── embedding.py     # Embedding model wrapper
│   │   ├── indexer.py       # Document indexing
│   │   ├── llm.py           # LLM wrapper
│   │   ├── reranker.py      # Reranking service
│   │   ├── router.py        # Intent classification
│   │   └── vlm.py           # Vision-language model support
│   └── memory/
│       ├── store.py         # LanceDB memory store
│       ├── auth_store.py    # User authentication store
│       └── sessions.py      # Session history store
├── models/                  # Data models
├── scripts/
│   └── model_download.py    # Model download utilities
├── static/                  # Served frontend files (production)
├── frontend/                # Vue 3 frontend source
├── docs/                    # Documentation
└── lancedb_db/              # Persistent vector store (auto-created)
```

## Frontend Structure

```
frontend/
├── src/
│   ├── App.vue                 # Root component
│   ├── main.ts                 # Entry point
│   ├── style.css               # Global styles
│   ├── api/
│   │   └── client.ts           # API client with JWT auth
│   ├── components/
│   │   ├── ImportDocumentsPanel.vue
│   │   ├── MemoryDetailPanel.vue
│   │   ├── MemoryList.vue
│   │   ├── SessionSidebar.vue
│   │   └── TopBar.vue
│   ├── composables/
│   │   └── useChatStream.ts    # Chat streaming logic
│   ├── router/
│   │   └── index.ts            # Vue Router configuration
│   ├── stores/
│   │   ├── auth.ts             # Pinia auth store
│   │   └── channels.ts         # Pinia channel/project store
│   └── views/
│       ├── ChannelAdminView.vue
│       ├── ChannelListView.vue
│       ├── ChatView.vue
│       └── LoginView.vue
```

## Authentication Flow

1. User logs in via `/api/auth/login` with Shiratsuyu credentials
2. Server validates against Shiratsuyu API and returns JWT token
3. Frontend stores token in Pinia auth store
4. Subsequent requests include `Authorization: Bearer <token>` header
5. Server validates JWT and extracts user info from `auth_store`
6. User groups determine channel/admin permissions

## Telegram Bot Setup

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Set `TELEGRAM_BOT_TOKEN` in `.env`
3. Set `TELEGRAM_ACCESS_CODE` for admin access
4. Bot will automatically start and listen for messages
5. Users can authenticate via `/auth` command

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

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
