"""Settings. Secrets come from the environment only."""
import os
from dataclasses import dataclass

MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    token_ttl_minutes: int = 60
    db_path: str = "hr_chat.db"
    lockout_max_failures: int = 5
    lockout_window_minutes: int = 10
    lockout_duration_minutes: int = 15
    chat_rate_limit_per_minute: int = 30
    answer_model: str = "claude-sonnet-5-5"
    router_model: str = "claude-haiku-5-5"
    demo_mode: bool = False  # lists demo accounts on the login page; never enable in production

    def __post_init__(self) -> None:
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters long.")

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("JWT_SECRET")
        if not secret:
            raise ValueError("JWT_SECRET is not set. Copy .env.example to .env and set it.")
        return cls(
            jwt_secret=secret,
            token_ttl_minutes=int(os.environ.get("TOKEN_TTL_MINUTES", "60")),
            db_path=os.environ.get("DB_PATH", "hr_chat.db"),
            answer_model=os.environ.get("ANSWER_MODEL", "claude-sonnet-5-5"),
            router_model=os.environ.get("ROUTER_MODEL", "claude-haiku-5-5"),
            demo_mode=os.environ.get("DEMO_DATA", "true").lower() != "false",
        )
