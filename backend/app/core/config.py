from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")
    DATABASE_URL: str = "mysql+aiomysql://ragent:ragent123@localhost:3307/ragent?charset=utf8mb4"

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    SECRET_KEY: str = "change-me-to-a-random-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 小时

    # LLM
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    DEEPSEEK_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Embedding（支持 openai / dashscope / fake）
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # 文档处理
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    MAX_UPLOAD_SIZE_MB: int = 50

    # 上传
    UPLOAD_DIR: str = "uploads"

    # 检索
    RETRIEVAL_TOP_K: int = 5


@lru_cache()
def get_settings() -> Settings:
    return Settings()
