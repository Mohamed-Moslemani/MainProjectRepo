import re
from pydantic import BaseModel, EmailStr, field_validator
from datetime import date


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v
    full_name: str
    father_name: str | None = None
    mother_name: str | None = None
    date_of_birth: date | None = None
    place_of_birth: str | None = None
    gender: str | None = None
    registry_number: str | None = None
    registry_place: str | None = None
    phone: str | None = None
    address: str | None = None
    marital_status: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: str
    email: str
    email_verified: bool
    full_name: str
    father_name: str | None
    mother_name: str | None
    date_of_birth: date | None
    place_of_birth: str | None
    gender: str | None
    registry_number: str | None
    registry_place: str | None
    phone: str | None
    address: str | None
    marital_status: str | None
    religious_sect: str | None = None
    role: str

    model_config = {"from_attributes": True}


class ProfileUpdateRequest(BaseModel):
    """Editable subset of the user profile.

    Email + full_name + identity numbers (registry / DOB) are
    intentionally NOT here — those are identity fields the citizen
    declared at registration and should only be changed through a
    formal identity-correction flow, not by editing a profile form.
    """
    phone: str | None = None
    address: str | None = None
    marital_status: str | None = None
    place_of_birth: str | None = None
    # Religious sect (مذهب) — Lebanese civil records carry this.
    # Validated against the 18-sect whitelist server-side.
    religious_sect: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
