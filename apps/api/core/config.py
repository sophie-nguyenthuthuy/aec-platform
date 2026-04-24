from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aec:aec@localhost:5432/aec"
    database_url_sync: str = "postgresql://aec:aec@localhost:5432/aec"
    redis_url: str = "redis://localhost:6379/0"

    supabase_jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    openai_embedding_model: str = "text-embedding-3-large"

    aws_region: str = "ap-southeast-1"
    s3_bucket: str = "aec-platform-files"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "no-reply@aec-platform.vn"

    cors_origins: list[str] = ["http://localhost:3000"]

    # SiteEye Ray Serve (YOLOv8m safety model). Read by apps.ml.pipelines.siteeye.
    # Override via env `SITEEYE_RAY_SERVE_URL` in deployment manifests.
    siteeye_ray_serve_url: str = "http://siteeye-safety:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
