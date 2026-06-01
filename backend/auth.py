"""
auth.py — JWT creation, verification, password hashing, RBAC dependencies
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import get_user_by_id
from models import Role

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SECRET_KEY      = os.getenv("JWT_SECRET_KEY", "change-this-in-production-min-32-chars")
ALGORITHM       = "HS256"
TOKEN_EXPIRE_HR = 24

pwd_context  = CryptContext(schemes=["bcrypt"], deprecated="auto")
http_bearer  = HTTPBearer()


# ── Password ──────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, role: str) -> str:
    expire  = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HR)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── Current user dependency ───────────────────────────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(http_bearer)
) -> dict:
    token   = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── RBAC dependencies ─────────────────────────────────────────────────────────
def require_analyst(user: dict = Depends(get_current_user)) -> dict:
    """Analyst and admin can access. Viewer gets 403."""
    if user["role"] not in [Role.analyst, Role.admin]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst or Admin role required"
        )
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Admin only."""
    if user["role"] != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required"
        )
    return user