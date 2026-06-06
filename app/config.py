from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/sendit"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    scrape_timeout_seconds: float = 30.0
    # Proxy HTTP(S) optionnel — si Gartner renvoie 403 depuis l'IP serveur (SCRAPE_HTTP_PROXY).
    scrape_http_proxy: str | None = None
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"


settings = Settings()
