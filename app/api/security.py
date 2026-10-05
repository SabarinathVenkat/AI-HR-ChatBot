"""Password hashing and JWT handling."""
from datetime import datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings

_hasher = PasswordHasher()


class InvalidToken(Exception):
    pass


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


def create_token(settings: Settings, employee_id: int, role: str, now: datetime) -> str:
    expires = now + timedelta(minutes=settings.token_ttl_minutes)
    claims = {"sub": str(employee_id), "role": role, "iat": now, "exp": expires}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str, now: datetime) -> int:
    """Return the employee id. Expiry is checked against `now` so tests can control time."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # pinned: 'none' and others are refused
            options={"require": ["exp", "sub"], "verify_exp": False},
        )
        if claims["exp"] <= now.timestamp():
            raise InvalidToken("expired")
        return int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise InvalidToken(str(exc)) from exc
