from pydantic import BaseModel
from datetime import datetime


class PaymentCreate(BaseModel):
    case_id: str


class PaymentResponse(BaseModel):
    id: str
    case_id: str
    amount: int
    currency: str
    status: str
    checkout_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
