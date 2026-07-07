from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    OLLAMA_CHAT_URL: str
    OLLAMA_BEARER: str
    CHAT_MODEL: str
    CHAT_MODEL_ROUTER: str
    CHAT_MODEL_THINK: bool = False
    EMBEDDING_MODEL: str
    CHROMA_PERSIST_PATH: str = "./chroma_db"


settings = Settings()
