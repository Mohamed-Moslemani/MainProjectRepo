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

    # Face quality thresholds (from Rekognition DetectFaces)
    min_face_confidence: float = 90.0
    min_brightness: float = 20.0
    min_sharpness: float = 20.0

    model_config = {"env_prefix": "FACE_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
