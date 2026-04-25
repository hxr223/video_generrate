from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Video Generation Platform"
    app_env: str = "local"
    log_level: str = "INFO"

    ark_api_key: str | None = None
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    seedance_model: str = "doubao-seedance-1-0-pro-250528"
    seedance_api_base_url: str | None = "https://operator.las.cn-beijing.volces.com/api/v1"
    seedance_submit_path: str = "/contents/generations/tasks"
    seedance_query_path_template: str = "/contents/generations/tasks/{task_id}"
    seedance_poll_interval_seconds: int = 10
    seedance_max_poll_attempts: int = 90
    seedream_model: str = "doubao-seedream-4-5-251128"
    seedream_api_base_url: str | None = "https://operator.las.cn-beijing.volces.com/api/v1"
    seedream_submit_path: str = "/images/generations"
    seedream_size: str = "1024x1024"

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/video_platform"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "video-platform"
    minio_region: str = "us-east-1"
    object_storage_public_base_url: str | None = None

    local_render_dir: str = "tmp/renders"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
