"""
VERIFUSE V2 — Authentication Module

JWT-based auth with bcrypt password hashing.
Provides register, login, and token verification.
"""

from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request

from verifuse_v2.db import database as db

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

JWT_SECRET = os.getenv("VERIFUSE_JWT_SECRET", "vf2-dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # 3-day tokens


# ── Password hashing ────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT tokens ───────────────────────────────────────────────────────

def create_token(user_id: str, email: str, tier: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "tier": tier,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


# ── Request helpers ──────────────────────────────────────────────────

def get_current_user(request: Request) -> dict:
    """Extract and validate the JWT from the Authorization header.

    Returns the full user dict from the database.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token.")

    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token)

    user = db.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated.")

    return user


def get_optional_user(request: Request) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None


def require_admin(request: Request) -> dict:
    """Require admin privileges. Returns user dict or raises 403."""
    user = get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def is_admin_user(user: dict) -> bool:
    """Check if a user has admin privileges."""
    return bool(user.get("is_admin", 0))


def verify_attorney(user: dict) -> bool:
    """Check if a user has a verified bar number."""
    return bool(user.get("bar_number") and str(user["bar_number"]).strip())


# ── Registration & Login ─────────────────────────────────────────────

def register_user(
    email: str,
    password: str,
    full_name: str = "",
    firm_name: str = "",
    bar_number: str = "",
    tier: str = "recon",
) -> tuple[dict, str]:
    """Register a new user. Returns (user_dict, jwt_token).

    Raises HTTPException if email already exists.
    """
    existing = db.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered.")

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user_id = str(uuid.uuid4())
    password_hashed = hash_password(password)

    user = db.create_user(
        user_id=user_id,
        email=email,
        password_hash=password_hashed,
        full_name=full_name,
        firm_name=firm_name,
        bar_number=bar_number,
        tier=tier,
    )

    token = create_token(user_id, email, tier)
    log.info("New user registered: %s (%s)", email, tier)
    return user, token


def login_user(email: str, password: str) -> tuple[dict, str]:
    """Authenticate a user. Returns (user_dict, jwt_token).

    Raises HTTPException on failure.
    """
    user = db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated.")

    db.update_user_login(user["user_id"])
    token = create_token(user["user_id"], email, user["tier"])
    log.info("User logged in: %s", email)
    return user, token
