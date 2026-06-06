"""
models.py — Pydantic models with password validation
"""
from pydantic import BaseModel, EmailStr, field_validator
from enum import Enum


class Role(str, Enum):
    admin   = "admin"
    analyst = "analyst"
    viewer  = "viewer"


# ── Auth models ───────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email:    EmailStr
    password: str
    role:     Role = Role.viewer

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    role:         str


class UserResponse(BaseModel):
    id:    str
    email: str
    role:  str


# ── RAG models ────────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer:  str
    sources: list[str]


class IngestRequest(BaseModel):
    urls: list[str]


class IngestResponse(BaseModel):
    message: str