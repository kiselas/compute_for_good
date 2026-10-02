import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://cfg:cfg-local@localhost:55471/cfg")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:56381/0")
    demo_mode: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
    public_url: str = os.getenv("PUBLIC_URL", "http://localhost:8010").rstrip("/")
    cors_origins: tuple[str, ...] = tuple(os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    lease_seconds: int = int(os.getenv("LEASE_SECONDS", "5400"))
    max_lease_seconds: int = int(os.getenv("MAX_LEASE_SECONDS", "21600"))
    permit_seconds: int = int(os.getenv("PERMIT_SECONDS", "600"))
    frontend_url: str = os.getenv("FRONTEND_URL", os.getenv("PUBLIC_URL", "http://localhost:5173")).rstrip("/")
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true" or os.getenv("PUBLIC_URL", "").startswith("https://")
    github_client_id: str = os.getenv("GITHUB_CLIENT_ID", "")
    github_client_secret: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    registration_enabled: bool = os.getenv("REGISTRATION_ENABLED", "true").lower() == "true"
    oauth_secret_key: str = os.getenv("OAUTH_SECRET_KEY", "")


settings = Settings()
