"""
auth.py
=======
FastAPI APIRouter: User Authentication (#11)
JWT-based authentication with bcrypt password hashing.
Endpoints:
  POST /auth/register  - create account
  POST /auth/login     - get JWT token
  GET  /auth/me        - get current user info
  POST /auth/refresh   - refresh token
  PUT  /auth/password  - change password

Users stored in analyses.db (users table).
Token expiry: 24 hours (configurable via .env JWT_EXPIRE_HOURS).
"""

import sqlite3
import bcrypt
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from jose import jwt, JWTError

router  = APIRouter()
DB_PATH = "backend/demo1/analyses.db"
bearer  = HTTPBearer(auto_error=False)

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_KEY   = os.getenv("JWT_SECRET_KEY", "nlp-portfolio-secret-change-in-production")
ALGORITHM    = "HS256"
EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


# ── DB Setup ───────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            email        TEXT    UNIQUE NOT NULL,
            password_hash TEXT   NOT NULL,
            role         TEXT    DEFAULT 'user',
            active       INTEGER DEFAULT 1,
            created_at   TEXT    NOT NULL,
            last_login   TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[Auth] Users table initialized ✓")


# ── Password helpers ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ── JWT helpers ────────────────────────────────────────────────────────────────

def create_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS)
    payload = {
        "sub":      str(user_id),
        "username": username,
        "role":     role,
        "exp":      expire,
        "iat":      datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(401, f"Invalid or expired token: {e}")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    """Dependency — inject into any endpoint to require authentication."""
    if not credentials:
        raise HTTPException(401, "Authentication required. Pass Bearer token.")
    payload = decode_token(credentials.credentials)
    user_id = int(payload.get("sub", 0))

    conn = get_conn()
    user = conn.execute(
        "SELECT id, username, email, role, active, created_at, last_login FROM users WHERE id=?",
        (user_id,)
    ).fetchone()
    conn.close()

    if not user:
        raise HTTPException(401, "User not found")
    if not user["active"]:
        raise HTTPException(403, "Account is deactivated")

    return dict(user)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency — require admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return current_user


# ── Pydantic models ────────────────────────────────────────────────────────────

class RegisterBody(BaseModel):
    username: str
    email:    str
    password: str
    role:     Optional[str] = "user"

class LoginBody(BaseModel):
    username: str
    password: str

class ChangePasswordBody(BaseModel):
    current_password: str
    new_password:     str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/register")
def register(body: RegisterBody):
    """Create a new user account."""
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if len(body.username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if "@" not in body.email:
        raise HTTPException(400, "Invalid email address")

    hashed = hash_password(body.password)
    conn   = get_conn()

    # Check for duplicates
    existing = conn.execute(
        "SELECT id FROM users WHERE username=? OR email=?",
        (body.username, body.email)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, "Username or email already registered")

    cur = conn.execute("""
        INSERT INTO users (username, email, password_hash, role, created_at)
        VALUES (?,?,?,?,?)
    """, (
        body.username, body.email, hashed,
        body.role if body.role in ("user", "admin") else "user",
        datetime.now(timezone.utc).isoformat()
    ))
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    token = create_token(user_id, body.username, "user")

    return {
        "success":  True,
        "message":  f"Account created for '{body.username}'",
        "user_id":  user_id,
        "username": body.username,
        "token":    token,
        "expires_in_hours": EXPIRE_HOURS,
    }


@router.post("/login")
def login(body: LoginBody):
    """Authenticate and receive a JWT token."""
    conn = get_conn()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND active=1",
        (body.username,)
    ).fetchone()

    if not user or not verify_password(body.password, user["password_hash"]):
        conn.close()
        raise HTTPException(401, "Invalid username or password")

    # Update last login
    conn.execute(
        "UPDATE users SET last_login=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(), user["id"])
    )
    conn.commit()
    conn.close()

    token = create_token(user["id"], user["username"], user["role"])

    return {
        "success":  True,
        "token":    token,
        "token_type": "bearer",
        "username": user["username"],
        "role":     user["role"],
        "expires_in_hours": EXPIRE_HOURS,
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user info."""
    return {
        "success":    True,
        "user":       {
            "id":         current_user["id"],
            "username":   current_user["username"],
            "email":      current_user["email"],
            "role":       current_user["role"],
            "created_at": current_user["created_at"],
            "last_login": current_user["last_login"],
        }
    }


@router.post("/refresh")
def refresh_token(current_user: dict = Depends(get_current_user)):
    """Issue a fresh token for the current user."""
    token = create_token(
        current_user["id"],
        current_user["username"],
        current_user["role"]
    )
    return {
        "success": True,
        "token":   token,
        "expires_in_hours": EXPIRE_HOURS,
    }


@router.put("/password")
def change_password(body: ChangePasswordBody,
                    current_user: dict = Depends(get_current_user)):
    """Change the current user's password."""
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    conn = get_conn()
    user = conn.execute(
        "SELECT password_hash FROM users WHERE id=?", (current_user["id"],)
    ).fetchone()

    if not verify_password(body.current_password, user["password_hash"]):
        conn.close()
        raise HTTPException(401, "Current password is incorrect")

    new_hash = hash_password(body.new_password)
    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (new_hash, current_user["id"])
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": "Password updated successfully"}


@router.get("/users")
def list_users(current_user: dict = Depends(require_admin)):
    """List all users — admin only."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, email, role, active, created_at, last_login FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return {
        "success": True,
        "count":   len(rows),
        "users":   [dict(r) for r in rows],
    }
