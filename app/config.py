from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_url: str = "postgresql://postgres:postgres@db:5432/voxo"
    redis_host: str = "redis"
    redis_port: int = 6379

    voxo_api_token: str   # Bearer token — paste from Voxo portal

    openai_api_key: str

    sync_lookback_days: int = 30

    model_config = {"env_file": ".env"}


settings = Settings()
