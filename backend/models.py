"""
models.py — Pydantic models for request/response validation
"""
from pydantic import BaseModel, EmailStr
from enum import Enum
from typing import Optional


class Role(str, Enum):
    admin   = "admin"
    analyst = "analyst"
    viewer  = "viewer"


# ── Auth models ───────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email:    EmailStr
    password: str
    role:     Role = Role.viewer


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