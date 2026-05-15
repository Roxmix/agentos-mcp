"""
AgentOS Configuration Module

All settings are loaded from environment variables or .env file
using pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Server
    agentos_host: str = "127.0.0.1"
    agentos_port: int = 8765
    agentos_server_name: str = "agentos"

    # Database
    database_url: str = "sqlite:///./agentos.db"

    # Vector Store (ChromaDB)
    chroma_persist_dir: str = "./chroma_store"
    chroma_collection_name: str = "agentos_memories"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # Memory Settings
    memory_decay_rate: float = 0.01
    memory_max_per_agent: int = 10000

    # Reflection
    reflection_lookback_days: int = 7
    pattern_min_frequency: int = 3

    # Logging
    log_level: str = "INFO"
    log_file: str = "./agentos.log"

    # Gateway
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8080
    gateway_secret: str = ""

    # Webhook
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
