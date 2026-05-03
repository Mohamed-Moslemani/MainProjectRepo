from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    google_credentials_path: str = "/app/credentials/google-vision.json"
    min_confidence_threshold: float = 0.7
    # Laplacian variance threshold. Phone-camera captures of LB ID
    # cards land in the 40-90 range in normal indoor light; below ~25
    # is where OCR genuinely struggles. The previous value (100) was
    # calibrated for desktop scans and rejected legitimate captures.
    # Override via OCR_BLUR_THRESHOLD env var on a per-deploy basis.
    blur_threshold: float = 30.0
    min_resolution_width: int = 640
    min_resolution_height: int = 480

    # When True, extract_text and assess_quality return deterministic
    # fixture data instead of calling Google Vision / cv2.
    # Lets E2E tests run offline without burning API credits.
    mock_mode: bool = False

    # LLM-backed structured-field extraction. Used as a *fallback*
    # when the regex extractor leaves a table-shaped doc with too
    # few fields (Lebanese civil registry extracts in particular —
    # the form is a 3-column table that regex can't reliably parse).
    # Cost is ~$0.005/call, only paid when regex isn't enough.
    llm_fallback_enabled: bool = True
    llm_fallback_min_fields: int = 3
    llm_provider: str = "openai"            # only "openai" supported today
    llm_model: str = "gpt-4o-mini"
    # Read OPENAI_API_KEY from env directly (no OCR_ prefix) so it
    # matches the canonical OpenAI SDK env-var name.

    model_config = {"env_prefix": "OCR_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
