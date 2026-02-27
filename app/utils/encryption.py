import os
from cryptography.fernet import Fernet

def get_fernet():
    key = os.getenv("FERNET_KEY")
    if not key:
        raise ValueError("FERNET_KEY not set in environment variables")
    return Fernet(key.encode())

def encrypt(data: str) -> bytes:
    if not data:
        return None
    return get_fernet().encrypt(data.encode('utf-8'))

def decrypt(token: bytes) -> str:
    if not token:
        return None
    return get_fernet().decrypt(token).decode('utf-8')

def encrypt_file(file_bytes: bytes) -> bytes:
    return get_fernet().encrypt(file_bytes)

def decrypt_file(encrypted_bytes: bytes) -> bytes:
    return get_fernet().decrypt(encrypted_bytes)