from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.bot.bot import build_application, start_bot, stop_bot
from app.bot.telegram_sessions import telegram_session_manager
from app.core.config import settings
from app.memory.sessions import sessions_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    await sessions_store.init_db()
    await telegram_session_manager.initialize()

    telegram_app = None
    if settings.TELEGRAM_BOT_TOKEN:
        telegram_app = build_application(settings.TELEGRAM_BOT_TOKEN)
        await start_bot(telegram_app)

    yield

    if telegram_app is not None:
        await stop_bot(telegram_app)


app = FastAPI(title="LLM Project Secretary", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    from app.core.config import settings
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT)
