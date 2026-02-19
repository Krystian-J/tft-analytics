from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -------------------------------------------------------------------------
    # RIOT API
    # -------------------------------------------------------------------------
    RIOT_API_KEY: str
    RIOT_REGION: str = "europe"

    # -------------------------------------------------------------------------
    # POSTGRESQL
    # -------------------------------------------------------------------------
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_URL: str

    # -------------------------------------------------------------------------
    # CLICKHOUSE
    # -------------------------------------------------------------------------
    CLICKHOUSE_HOST: str
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_DB: str

    # -------------------------------------------------------------------------
    # REDIS
    # -------------------------------------------------------------------------
    REDIS_URL: str

    # -------------------------------------------------------------------------
    # CRAWLER
    # -------------------------------------------------------------------------
    RATE_LIMIT_BUFFER: int = 5
    CRAWLER_COOLDOWN_MINUTES: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Single instance imported across the entire project
settings = Settings()
