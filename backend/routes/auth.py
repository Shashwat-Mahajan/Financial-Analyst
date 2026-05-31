"""
routes/auth.py — /auth/register and /auth/login endpoints
"""
from fastapi import APIRouter, HTTPException, status
from auth import hash_password, verify_password, create_access_token
from database import create_user, get_user_by_email
from models import RegisterRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", status_code=201)
def register(body: RegisterRequest):
    """Register a new user. Default role is viewer."""
    existing = get_user_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    hashed = hash_password(body.password)
    user   = create_user(body.email, hashed, body.role.value)
    if not user:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return {
        "message": "User registered successfully",
        "email":   user["email"],
        "role":    user["role"],
    }


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Login with email and password. Returns JWT token."""
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    token = create_access_token(str(user["id"]), user["role"])
    return TokenResponse(access_token=token, role=user["role"])