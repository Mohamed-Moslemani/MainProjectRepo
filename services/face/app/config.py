from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AWS Rekognition
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Thresholds - conservative: borderline goes to manual review
    similarity_pass_threshold: float = 90.0      # above = pass
    similarity_review_threshold: float = 70.0     # between review and pass = manual review
    # below review threshold = fail

    liveness_pass_threshold: float = 0.85
    liveness_review_threshold: float = 0.5

    model_config = {"env_prefix": "FACE_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
