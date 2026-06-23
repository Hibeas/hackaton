"""JWT auth helpers and password hashing."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt

from voice_call_service import normalize_phone_number, validate_phone_number
from user_store import user_store

bearer_scheme = HTTPBearer(auto_error=False)

JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "10080"))  # 7 days
MIN_PASSWORD_LENGTH = 8


def auth_configured() -> bool:
    return bool(JWT_SECRET)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("weak_password")


def create_access_token(*, user_id: str, email: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("auth_not_configured")
    expires = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="auth_not_configured")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc


def public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row.get("full_name"),
        "phone_e164": row.get("phone_e164"),
        "created_at": row.get("created_at"),
    }


def validate_phone(phone: str) -> str:
    try:
        return validate_phone_number(normalize_phone_number(phone))
    except ValueError as exc:
        raise ValueError("invalid_phone") from exc


def register_user(
    *,
    email: str,
    password: str,
    phone_e164: str,
    full_name: str | None = None,
) -> dict[str, Any]:
    validate_password_strength(password)
    normalized_phone = validate_phone(phone_e164)
    password_hash = hash_password(password)
    user = user_store.create_user(
        email=email,
        password_hash=password_hash,
        phone_e164=normalized_phone,
        full_name=full_name.strip() if full_name else None,
    )
    token = create_access_token(user_id=user["id"], email=user["email"])
    return {"access_token": token, "token_type": "bearer", "user": user}


def login_user(*, email: str, password: str) -> dict[str, Any]:
    row = user_store.get_by_email(email)
    if row is None or not verify_password(password, row["password_hash"]):
        raise ValueError("invalid_credentials")
    user = public_user(row)
    token = create_access_token(user_id=user["id"], email=user["email"])
    return {"access_token": token, "token_type": "bearer", "user": user}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="missing_token")
    payload = decode_access_token(credentials.credentials)
    user_id = str(payload.get("sub") or "")
    row = user_store.get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=401, detail="user_not_found")
    return public_user(row)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any] | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None
