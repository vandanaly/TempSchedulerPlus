from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import config

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None
    storage = None

try:
    from google.api_core.exceptions import GoogleAPICallError, PermissionDenied
except ImportError:
    GoogleAPICallError = Exception
    PermissionDenied = Exception


_INITIALIZED = False


def _firebase_key_path() -> Path:
    configured = getattr(config, "FIREBASE_KEY_PATH", config.BASE_DIR / "firebase_key.json")
    return Path(configured)


def _project_id_from_key() -> str:
    key_path = _firebase_key_path()
    if not key_path.exists():
        return ""
    try:
        payload = json.loads(key_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("project_id", "")).strip()


def _bucket_name() -> str:
    configured_bucket = str(getattr(config, "FIREBASE_STORAGE_BUCKET", "")).strip()
    if configured_bucket:
        return configured_bucket

    project_id = _project_id_from_key()
    if not project_id:
        return ""
    return f"{project_id}.appspot.com"


def _metadata_collection() -> str:
    return str(getattr(config, "FIREBASE_METADATA_COLLECTION", "files")).strip() or "files"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_initialized() -> bool:
    global _INITIALIZED

    if _INITIALIZED:
        return True
    if firebase_admin is None:
        return False
    if not _bucket_name():
        return False

    key_path = _firebase_key_path()
    if not key_path.exists():
        return False

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(
            cred,
            {
                "storageBucket": _bucket_name(),
            },
        )

    _INITIALIZED = True
    return True


def upload_to_cloud(file_path: str | Path):
    if not _ensure_initialized():
        return None

    source = Path(file_path)
    if not source.exists():
        raise FileNotFoundError(f"Upload skipped. File not found: {source}")

    try:
        blob = storage.bucket().blob(f"cold_data/{source.name}")
        blob.upload_from_filename(str(source))
        print(f"Uploaded to cloud: {source}")
        return blob.name
    except (PermissionDenied, GoogleAPICallError, OSError, ValueError):
        return None


def download_from_cloud(filename: str, destination_dir: str | Path | None = None):
    if not _ensure_initialized():
        return None

    target_dir = Path(destination_dir) if destination_dir else config.EDGE
    target_dir.mkdir(parents=True, exist_ok=True)

    destination = target_dir / filename
    blob = storage.bucket().blob(f"cold_data/{filename}")
    blob.download_to_filename(str(destination))

    print(f"Downloaded: {filename}")
    return str(destination)


def store_metadata(name: str, size: int, tier: str, details: dict | None = None):
    if not _ensure_initialized():
        return None

    payload = {
        "name": name,
        "size": int(size),
        "tier": tier,
        "created_at": _utc_now_iso(),
        "details": details or {},
    }
    try:
        _, doc_ref = firestore.client().collection(_metadata_collection()).add(payload)
        return doc_ref.id
    except (PermissionDenied, GoogleAPICallError, OSError, ValueError):
        return None


def list_metadata(limit: int = 500):
    if not _ensure_initialized():
        return []

    result = []
    try:
        docs = firestore.client().collection(_metadata_collection()).limit(int(limit)).stream()
        for doc in docs:
            payload = doc.to_dict() or {}
            payload["id"] = doc.id
            result.append(payload)
    except (PermissionDenied, GoogleAPICallError, OSError, ValueError):
        return []
    return result


def firebase_is_configured() -> bool:
    return bool(_bucket_name()) and _firebase_key_path().exists() and firebase_admin is not None
