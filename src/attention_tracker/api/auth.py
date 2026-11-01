"""Per-device bearer tokens. Only the SHA-256 of a token is stored."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from attention_tracker.storage.repository import Repository


@dataclass(frozen=True)
class Device:
    device_id: str
    user_id: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_device(repo: Repository, user_id: str) -> tuple[str, str]:
    """Create the user if needed, register a new device and return (device_id, plaintext token).
    The plaintext token is returned exactly once and never stored."""
    repo.create_user(user_id)
    device_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    repo.create_device(device_id, user_id, hash_token(token))
    return device_id, token


def make_current_device(repo: Repository):
    bearer = HTTPBearer(auto_error=False)

    def current_device(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Device:
        unauthorized = HTTPException(
            status_code=401,
            detail="missing or invalid device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if creds is None or creds.scheme.lower() != "bearer":
            raise unauthorized
        row = repo.device_for_token_hash(hash_token(creds.credentials))
        if row is None:
            raise unauthorized
        return Device(device_id=row["device_id"], user_id=row["user_id"])

    return current_device
