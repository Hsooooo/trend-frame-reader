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
    deepl_api_key: str = ""
    deepl_api_url: str = "https://api-free.deepl.com/v2/translate"
    deepl_timeout_seconds: float = 6.0
    deepl_retries: int = 1
    openai_api_key: str = ""
    openai_keyword_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 10.0
    cors_allowed_origins: str = ""
    admin_token: str = ""
    mongodb_uri: str = ""
    mongodb_database: str = "trend_frame_graph"
    openai_embedding_model: str = "text-embedding-3-small"
    rag_top_k: int = 5
    rag_bm25_index: str = "search_index"
    rag_vec_candidates: int = 20
    rag_bm25_candidates: int = 20
    rag_w_vector: float = 0.6
    rag_w_bm25: float = 0.4
    rag_min_evidence: int = 2
    rag_similarity_threshold: float = 0.3
    graph_backfill_batch_size: int = 50
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    jwt_secret: str = ""
    jwt_expire_days: int = 30
    frontend_url: str = "http://localhost:3000"

    def cors_origins(self) -> list[str]:
        if not self.cors_allowed_origins.strip():
            return []
        return [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]


settings = Settings()
