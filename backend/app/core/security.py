from datetime import datetime, timedelta
from typing import Any

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY.encode() if settings.ENCRYPTION_KEY else Fernet.generate_key()
        _fernet = Fernet(key)
    return _fernet


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"exp": expire, "sub": str(subject)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def encrypt_credential(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_credential(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()
