from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    google_credentials_path: str = "/app/credentials/google-vision.json"
    min_confidence_threshold: float = 0.7
    blur_threshold: float = 100.0  # Laplacian variance threshold
    min_resolution_width: int = 640
    min_resolution_height: int = 480

    # When True, extract_text and assess_quality return deterministic
    # fixture data instead of calling Google Vision / cv2.
    # Lets E2E tests run offline without burning API credits.
    mock_mode: bool = False

    model_config = {"env_prefix": "OCR_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
