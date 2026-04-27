import base64
import hashlib
import hmac
import secrets


PASSWORD_HASH_PREFIX = 'pbkdf2_sha256'
PASSWORD_HASH_ITERATIONS = 310000


def _encode(value): return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decode(value): return base64.urlsafe_b64decode((value + '=' * (-len(value) % 4)).encode('ascii'))


def is_password_hash(value): return isinstance(value, str) and value.startswith(PASSWORD_HASH_PREFIX + '$')


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f'{PASSWORD_HASH_PREFIX}${PASSWORD_HASH_ITERATIONS}'
        f'${_encode(salt)}${_encode(digest)}'
    )

def verify_password(password, stored_password):
    if not stored_password:
        return False
    if not is_password_hash(stored_password):
        return hmac.compare_digest(password, stored_password)

    try:
        prefix, iterations, salt, digest = stored_password.split('$', 3)
        if prefix != PASSWORD_HASH_PREFIX:
            return False
        candidate = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            _decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(_encode(candidate), digest)
    except (ValueError, TypeError):
        return False

def password_needs_hash(stored_password):
    return bool(stored_password) and not is_password_hash(stored_password)
