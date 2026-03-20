from dataclasses import dataclass
import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    hindsight_base_url: str
    hindsight_api_key: str
    hindsight_bank_prefix: str
    groq_api_key: str
    groq_model: str
    default_timezone: str
    reminder_hour_utc: int
    openai_api_key: str
    openai_transcribe_model: str
    webhook_mode: bool
    webhook_listen: str
    webhook_port: int
    webhook_path: str
    webhook_public_url: str


    @staticmethod
    def from_env() -> "Settings":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")

        return Settings(
            telegram_bot_token=token,
            hindsight_base_url=os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888").strip(),
            hindsight_api_key=os.getenv("HINDSIGHT_API_KEY", "").strip(),
            hindsight_bank_prefix=os.getenv("HINDSIGHT_BANK_PREFIX", "tg-group").strip(),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
            default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC").strip(),
            reminder_hour_utc=int(os.getenv("REMINDER_HOUR_UTC", "9")),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_transcribe_model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1").strip(),
            webhook_mode=_env_bool("WEBHOOK_MODE", False),
            webhook_listen=os.getenv("WEBHOOK_LISTEN", "0.0.0.0").strip(),
            webhook_port=int(os.getenv("WEBHOOK_PORT", "8000")),
            webhook_path=os.getenv("WEBHOOK_PATH", "/telegram").strip() or "/telegram",
            webhook_public_url=os.getenv("WEBHOOK_PUBLIC_URL", "").strip(),
        )
