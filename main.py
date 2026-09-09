from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.auth_routes import router as auth_router
from app.api.routes import router
from app.bot.bot import build_application, start_bot, stop_bot
from app.bot.telegram_sessions import telegram_session_manager
from app.core.config import settings
from app.mcp.server import mcp
from app.memory.auth_store import auth_store
from app.memory.sessions import sessions_store

FRONTEND_DIST = Path(__file__).parent / "static"

mcp_app = mcp.streamable_http_app(json_response=True, streamable_http_path="/")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"INFO:\tServer running at http://127.0.0.1:{settings.PORT}{settings.ROOT_PATH}")
    await sessions_store.init_db()
    await auth_store.init_db()
    await telegram_session_manager.initialize()

    telegram_app = None
    if settings.TELEGRAM_BOT_TOKEN:
        telegram_app = build_application(settings.TELEGRAM_BOT_TOKEN)
        await start_bot(telegram_app)

    # The MCP sub-app is only mounted (not include_router'd), so its own lifespan never
    # runs unless we explicitly enter its session manager here.
    async with mcp.session_manager.run():
        yield

    if telegram_app is not None:
        await stop_bot(telegram_app)


app = FastAPI(title="Hirato Secretary", lifespan=lifespan, root_path=settings.ROOT_PATH)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

app.include_router(router)
app.include_router(auth_router)
app.mount("/mcp", mcp_app)


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str) -> FileResponse:
    """SPA fallback: serve a built frontend asset if it exists, else index.html for client-side routing."""
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    import uvicorn
    from app.core.config import settings
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, root_path=settings.ROOT_PATH)

