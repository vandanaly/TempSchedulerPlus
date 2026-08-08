from pathlib import Path

import config

try:
    from cryptography.fernet import Fernet
except ImportError as error:
    raise RuntimeError("cryptography is required for encryption") from error


KEY_PATH = config.ENCRYPTED / "fernet.key"


def _load_or_create_key():
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    return key


_cipher = Fernet(_load_or_create_key())


def encrypt_bytes(payload: bytes) -> bytes:
    return _cipher.encrypt(payload)


def decrypt_bytes(payload: bytes) -> bytes:
    return _cipher.decrypt(payload)


def encrypt_file(source_path, destination_path=None):
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"File not found for encryption: {source.name}")

    if destination_path is None:
        destination = config.ENCRYPTED / f"{source.stem}.enc"
    else:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

    encrypted = encrypt_bytes(source.read_bytes())
    destination.write_bytes(encrypted)
    return destination
