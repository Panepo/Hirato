from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.memory.sessions import sessions_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    await sessions_store.init_db()
    yield


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
