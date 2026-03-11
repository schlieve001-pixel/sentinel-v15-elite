"""
VERIFUSE V2 — Authentication Module

JWT-based auth with bcrypt password hashing.
Provides register, login, and token verification.
"""

from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from math import ceil
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request

from verifuse_v2.db import database as db

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

_JWT_DEFAULT = "vf2-dev-secret-change-in-production"
JWT_SECRET = os.getenv("VERIFUSE_JWT_SECRET", _JWT_DEFAULT)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # 3-day tokens

# Guard: reject weak default in production (non-dev environments)
_IS_PROD = os.getenv("VERIFUSE_ENV", "").lower() == "production"
if JWT_SECRET == _JWT_DEFAULT and _IS_PROD:
    raise RuntimeError(
        "SECURITY: VERIFUSE_JWT_SECRET not set — refusing to start in production with default secret."
    )
if JWT_SECRET == _JWT_DEFAULT:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "SECURITY WARNING: Using default JWT secret. Set VERIFUSE_JWT_SECRET before going to production."
    )


# ── Password hashing ────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT tokens ───────────────────────────────────────────────────────

def create_token(user_id: str, email: str, tier: str, role: str = "viewer", is_admin: bool = False, token_version: int = 0) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "tier": tier,
        "role": role,
        "is_admin": is_admin,
        "tv": token_version,  # token_version — increment to revoke all prior tokens
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

    # Token version check — revokes tokens issued before a password change or explicit logout
    token_tv = payload.get("tv", 0)
    db_tv = user.get("token_version") or 0
    if token_tv < db_tv:
        raise HTTPException(status_code=401, detail="Token revoked. Please log in again.")

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


# Role hierarchy: admin > staff > attorney > viewer
_ROLE_RANK = {"admin": 4, "staff": 3, "attorney": 2, "viewer": 1}


def _require_role(user: dict, min_role: str) -> None:
    """Raise 403 if user's role is below min_role in hierarchy.

    Backward-compat: is_admin=1 always passes any role check.
    """
    if user.get("is_admin"):
        return  # Admin passes everything
    role = user.get("role", "viewer")
    if _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(min_role, 0):
        raise HTTPException(
            status_code=403,
            detail=f"Requires {min_role} role or higher.",
        )


def verify_attorney(user: dict) -> bool:
    """Check if a user has a verified bar number."""
    return bool(user.get("bar_number") and str(user["bar_number"]).strip())


# ── Password validation ──────────────────────────────────────────────

def _validate_password(password: str) -> None:
    """Enforce complexity: 8+ chars, uppercase, number, special char."""
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("one uppercase letter")
    if not re.search(r"[0-9]", password):
        errors.append("one number")
    if not re.search(r"[^a-zA-Z0-9]", password):
        errors.append("one special character (!@#$%^&*...)")
    if errors:
        raise HTTPException(
            status_code=400,
            detail="Password must contain: " + ", ".join(errors),
        )


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

    _validate_password(password)

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

    token = create_token(user_id, email, tier, role=user.get("role", "viewer"), is_admin=bool(user.get("is_admin", 0)))
    log.info("New user registered: %s (%s)", email, tier)
    return user, token


def login_user(email: str, password: str) -> tuple[dict, str]:
    """Authenticate a user. Returns (user_dict, jwt_token).

    Raises HTTPException on failure. Implements 5-attempt lockout (15 min).
    """
    import sqlite3 as _sqlite3
    user = db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Check lockout
    locked_until = user.get("locked_until")
    now = datetime.now(timezone.utc)
    if locked_until:
        try:
            lu_dt = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
            if lu_dt.tzinfo is None:
                lu_dt = lu_dt.replace(tzinfo=timezone.utc)
            if lu_dt > now:
                minutes_left = ceil((lu_dt - now).total_seconds() / 60)
                raise HTTPException(
                    status_code=429,
                    detail=f"Account temporarily locked. Try again in {minutes_left} minute(s).",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # Malformed locked_until — treat as not locked

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated.")

    if not verify_password(password, user["password_hash"]):
        # Increment failed count
        conn = db.get_connection()
        try:
            new_count = (user.get("failed_login_count") or 0) + 1
            new_locked = None
            if new_count >= 5:
                new_locked = (now + timedelta(minutes=15)).isoformat()
            conn.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE user_id = ?",
                [new_count, new_locked, user["user_id"]],
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Success — reset lockout
    try:
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE user_id = ?",
                [user["user_id"]],
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

    db.update_user_login(user["user_id"])
    token = create_token(
        user["user_id"], email, user["tier"],
        role=user.get("role", "admin" if user.get("is_admin") else "viewer"),
        is_admin=bool(user.get("is_admin", 0)),
        token_version=user.get("token_version") or 0,
    )
    log.info("User logged in: %s", email)
    return user, token
