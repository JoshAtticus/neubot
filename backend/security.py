import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from backend.config import Config
from authlib.jose import jwt
import time

def generate_api_token(user_id: str) -> str:
    header = {'alg': 'HS256'}
    payload = {
        'sub': user_id,
        'iat': int(time.time()),
        # Token valid for 1 year
        'exp': int(time.time()) + 31536000
    }
    key = Config.SECRET_KEY
    return jwt.encode(header, payload, key).decode('utf-8')

def decode_api_token(token: str) -> str:
    try:
        key = Config.SECRET_KEY
        claims = jwt.decode(token, key)
        claims.validate()
        return claims['sub']
    except Exception:
        return None

def get_encryption_key(secret_key: str) -> bytes:
    salt = Config.TOKEN_ENCRYPTION_SALT
    if not salt:
        # Fallback if salt is not set, though it should be for persistence
        salt = b'default_salt' 
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))

def encrypt_token(token: str) -> str:
    key = get_encryption_key(Config.SECRET_KEY)
    fernet = Fernet(key)
    return fernet.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    key = get_encryption_key(Config.SECRET_KEY)
    fernet = Fernet(key)
    return fernet.decrypt(encrypted_token.encode()).decode()
