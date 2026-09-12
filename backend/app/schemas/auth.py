"""Pydantic schemas for authentication endpoints."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db.models.user import UserRole


def _validate_password_strength(value: str) -> str:
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit.")
    if not any(c.isalpha() for c in value):
        raise ValueError("Password must contain at least one letter.")
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    # The same rules as registration - a reset must not be a way to set a
    # weaker password than signup would have allowed.
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class VerifyEmailRequest(BaseModel):
    token: str


class LoginHistoryEntry(BaseModel):
    """One authentication event from this account's own history."""

    action: str
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserRead(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool
    is_verified: bool = False
    # Exposed so the client can present the right experience. This is a
    # convenience for the UI only - every admin capability is enforced
    # server-side regardless of what the client believes.
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
