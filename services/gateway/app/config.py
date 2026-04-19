import sys
from pathlib import Path
from functools import lru_cache

# Ensure the shared package is importable inside the container (/app/shared)
_shared_root = Path(__file__).resolve().parent.parent.parent
if str(_shared_root) not in sys.path:
    sys.path.insert(0, str(_shared_root))

from shared.config import get_env, load_env_file

# Load .env.dev (or .env) — existing env vars (e.g. set by Docker) take priority
load_env_file()


class Settings:
    """Gateway configuration built from environment variables."""

    def __init__(self):
        # Database
        self.database_url = get_env("GATEWAY_DATABASE_URL", "postgresql+asyncpg://docflow:docflow@db:5432/docflow")

        # JWT
        self.jwt_secret = get_env("GATEWAY_JWT_SECRET", "change-me-in-production")
        self.jwt_algorithm = get_env("GATEWAY_JWT_ALGORITHM", "HS256")
        self.jwt_expiry_minutes = int(get_env("GATEWAY_JWT_EXPIRY_MINUTES", "60"))
        self.jwt_refresh_expiry_days = int(get_env("GATEWAY_JWT_REFRESH_EXPIRY_DAYS", "7"))

        # Internal services
        self.ocr_service_url = get_env("GATEWAY_OCR_SERVICE_URL", "http://ocr:8001")
        self.face_service_url = get_env("GATEWAY_FACE_SERVICE_URL", "http://face:8002")

        # Stripe
        self.stripe_secret_key = get_env("GATEWAY_STRIPE_SECRET_KEY", "")
        self.stripe_webhook_secret = get_env("GATEWAY_STRIPE_WEBHOOK_SECRET", "")

        # Frontend origin used for building Stripe success/cancel URLs and
        # verification-email links. Falls back to the first CORS origin so
        # existing dev flows keep working even without the new env var.
        self.frontend_base_url = get_env(
            "GATEWAY_FRONTEND_BASE_URL",
            get_env("GATEWAY_CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")[0].strip(),
        )

        # File storage
        self.upload_dir = get_env("GATEWAY_UPLOAD_DIR", "/app/uploads")
        self.max_upload_size_mb = int(get_env("GATEWAY_MAX_UPLOAD_SIZE_MB", "10"))

        # Redis
        self.redis_url = get_env("GATEWAY_REDIS_URL", "redis://redis:6379/0")

        # Password reset
        self.reset_token_expiry_minutes = int(get_env("GATEWAY_RESET_TOKEN_EXPIRY_MINUTES", "15"))

        # Email verification
        self.verification_token_expiry_hours = int(get_env("GATEWAY_VERIFICATION_TOKEN_EXPIRY_HOURS", "24"))

        # SMTP
        self.smtp_host = get_env("GATEWAY_SMTP_HOST", "localhost")
        self.smtp_port = int(get_env("GATEWAY_SMTP_PORT", "587"))
        self.smtp_user = get_env("GATEWAY_SMTP_USER", "")
        self.smtp_password = get_env("GATEWAY_SMTP_PASSWORD", "")
        self.smtp_from_email = get_env("GATEWAY_SMTP_FROM_EMAIL", "noreply@docflow.lb")
        self.smtp_from_name = get_env("GATEWAY_SMTP_FROM_NAME", "DocFlow Lebanon")
        self.smtp_use_tls = get_env("GATEWAY_SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
        self.app_base_url = get_env("GATEWAY_APP_BASE_URL", "http://localhost:8000")

        # CORS
        self.cors_allowed_origins = get_env("GATEWAY_CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")

        # Rate limiting
        self.rate_limit_per_minute = int(get_env("GATEWAY_RATE_LIMIT_PER_MINUTE", "60"))
        self.rate_limit_login_per_minute = int(get_env("GATEWAY_RATE_LIMIT_LOGIN_PER_MINUTE", "10"))
        self.rate_limit_login_per_email_per_minute = int(get_env("GATEWAY_RATE_LIMIT_LOGIN_PER_EMAIL_PER_MINUTE", "5"))
        self.rate_limit_reset_per_ip_per_hour = int(get_env("GATEWAY_RATE_LIMIT_RESET_PER_IP_PER_HOUR", "5"))
        self.rate_limit_verification_per_ip_per_hour = int(get_env("GATEWAY_RATE_LIMIT_VERIFICATION_PER_IP_PER_HOUR", "5"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
