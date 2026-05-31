"""
database.py — Supabase connection and user operations
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(url, key)


def create_user(email: str, hashed_password: str, role: str) -> dict:
    supabase = get_supabase()
    result   = supabase.table("users").insert({
        "email":           email,
        "hashed_password": hashed_password,
        "role":            role,
    }).execute()
    return result.data[0] if result.data else None


def get_user_by_email(email: str) -> dict | None:
    supabase = get_supabase()
    result   = supabase.table("users").select("*").eq("email", email).execute()
    return result.data[0] if result.data else None


def get_user_by_id(user_id: str) -> dict | None:
    supabase = get_supabase()
    result   = supabase.table("users").select("*").eq("id", user_id).execute()
    return result.data[0] if result.data else None


def get_all_users() -> list[dict]:
    supabase = get_supabase()
    result   = supabase.table("users").select("id, email, role, created_at").execute()
    return result.data or []


def update_user_role(user_id: str, new_role: str) -> dict:
    supabase = get_supabase()
    result   = supabase.table("users").update({"role": new_role}).eq("id", user_id).execute()
    return result.data[0] if result.data else None