import base64
import hashlib
import hmac
import secrets

import bcrypt
from cryptography.fernet import Fernet


PASSWORD_PREFIX = "bcrypt_sha256$"


def _password_bytes(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds=12))
    return PASSWORD_PREFIX + hashed.decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    if not password_hash.startswith(PASSWORD_PREFIX):
        return False
    expected = password_hash.removeprefix(PASSWORD_PREFIX).encode("ascii")
    return bcrypt.checkpw(_password_bytes(password), expected)


def make_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "..."
    return f"{key[:7]}...{key[-6:]}"


def build_fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(value: str, app_secret_key: str) -> str:
    return build_fernet(app_secret_key).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str, app_secret_key: str) -> str:
    return build_fernet(app_secret_key).decrypt(value.encode("utf-8")).decode("utf-8")


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
