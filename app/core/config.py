from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    CHAT_MODEL: str = ""
    CHAT_BASE_URL: str = ""
    CHAT_API_KEY: str = ""

    ROUTER_MODEL: str = ""
    ROUTER_BASE_URL: str = ""
    ROUTER_API_KEY: str = ""

    EMBEDDING_MODEL: str = ""
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_API_KEY: str = ""

    VISION_CHAT_MODEL: str = ""
    VISION_CHAT_BASE_URL: str = ""
    VISION_CHAT_API_KEY: str = ""

    RERANKING_MODEL: str = ""
    RERANKING_BASE_URL: str = ""
    RERANKING_API_KEY: str = ""

    INDEXER_BASE_URL: str = ""
    INDEXER_API_KEY: str = ""

    SERVER_TIMEOUT: int = 600
    CHUNK_SIZE: int = 1024
    CHUNK_OVERLAP: int = 128
    VLM_TEMPERATURE: float = 0.1
    VLM_MAX_TOKENS: int = 8192

    CHROMA_PERSIST_PATH: str = "./chroma_db"
    SESSIONS_DB_PATH: str = "./sessions.db"

    PORT: int = 7950

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ACCESS_CODE: str = ""



settings = Settings()
