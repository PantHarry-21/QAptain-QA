from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from config import settings

_fernet: Optional[Fernet] = None


import os

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key_file = ".encryption_key"
        if settings.ENCRYPTION_KEY:
            key = settings.ENCRYPTION_KEY.encode()
        elif os.path.exists(key_file):
            with open(key_file, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, "wb") as f:
                f.write(key)
        _fernet = Fernet(key)
    return _fernet


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: Optional[Any], expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"exp": expire, "sub": str(subject)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def encrypt_credential(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_credential(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()
