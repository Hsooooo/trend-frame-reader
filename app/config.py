from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "trend-frame-reader-api"
    database_url: str = "postgresql+psycopg2://app:app@localhost:5432/trend_frame"
    app_timezone: str = "Asia/Seoul"
    feed_min_items: int = 3
    feed_max_items: int = 5
    feed_target_items_per_category: int = 3
    feed_max_items_per_category: int = 5
    feed_max_items_total: int = 30
    ingestion_lookback_hours: int = 48
    title_similarity_threshold: float = 0.85
    cors_allowed_origins: str = ""
    admin_token: str = ""

    def cors_origins(self) -> list[str]:
        if not self.cors_allowed_origins.strip():
            return []
        return [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]


settings = Settings()
