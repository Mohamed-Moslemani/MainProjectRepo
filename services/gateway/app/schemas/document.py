from pydantic import BaseModel
from datetime import datetime


class DocumentResponse(BaseModel):
    id: str
    case_id: str
    document_type: str
    original_filename: str
    file_size: int
    mime_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentWithOCR(DocumentResponse):
    ocr_status: str | None = None
    extracted_fields: dict | None = None
    confidence_scores: dict | None = None
    retake_required: bool = False
    retake_reasons: list[str] = []
