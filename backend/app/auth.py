"""Utilidades de autenticación.

Se evita agregar dependencias nuevas (bcrypt/JWT) para no complicar la
instalación en Windows: se usa PBKDF2-HMAC-SHA256 de la librería estándar
para las contraseñas, y un token aleatorio opaco guardado en la tabla
`usuarios` para las sesiones (suficiente para una demo académica).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


def generate_token() -> str:
    return secrets.token_urlsafe(32)
