from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import config

try:
    from supabase import create_client
except ImportError:
    create_client = None


_CLIENT = None
_LAST_UPLOAD_ERROR: str | None = None


def last_upload_error() -> str | None:
    return _LAST_UPLOAD_ERROR


def _supabase_url() -> str:
    return str(getattr(config, "SUPABASE_URL", "")).strip()


def _supabase_key() -> str:
    return str(getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")).strip()


def _bucket_name() -> str:
    return str(getattr(config, "SUPABASE_BUCKET_NAME", "")).strip()


def _bucket_prefix() -> str:
    return str(getattr(config, "SUPABASE_BUCKET_PREFIX", "cold_data")).strip() or "cold_data"


def _index_path() -> Path:
    return config.CLOUD / "index.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_local_index():
    path = _index_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def _save_local_index(records):
    _index_path().write_text(json.dumps(records, indent=2), encoding="utf-8")


def _client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if create_client is None:
        return None
    url = _supabase_url()
    key = _supabase_key()
    bucket = _bucket_name()
    if not url or not key or not bucket:
        return None
    try:
        _CLIENT = create_client(url, key)
        return _CLIENT
    except Exception:
        return None


def supabase_is_configured() -> bool:
    return bool(_supabase_url() and _supabase_key() and _bucket_name() and create_client is not None)


def upload_to_cloud(file_path: str | Path):
    global _LAST_UPLOAD_ERROR
    _LAST_UPLOAD_ERROR = None

    client = _client()
    if client is None:
        _LAST_UPLOAD_ERROR = "Supabase client not configured (check URL, key, and bucket name)."
        return None

    key = _supabase_key()
    if not (key.startswith("eyJ") or key.startswith("sb_secret_")):
        _LAST_UPLOAD_ERROR = (
            "Storage upload requires SUPABASE_SERVICE_ROLE_KEY (JWT starting with eyJ or sb_secret_). "
            "A publishable key is configured instead."
        )
        return None

    source = Path(file_path)
    if not source.exists():
        raise FileNotFoundError(f"Upload skipped. File not found: {source}")

    object_name = f"{_bucket_prefix()}/{source.name}"
    bucket = client.storage.from_(_bucket_name())
    try:
        with source.open("rb") as file_handle:
            bucket.upload(
                path=object_name,
                file=file_handle,
                file_options={"content-type": "application/octet-stream", "upsert": "true"},
            )
    except Exception as exc:
        _LAST_UPLOAD_ERROR = f"{type(exc).__name__}: {exc}"
        return None
    return object_name


def download_from_cloud(filename: str, destination_dir: str | Path | None = None):
    client = _client()
    if client is None:
        return None

    target_dir = Path(destination_dir) if destination_dir else config.EDGE
    target_dir.mkdir(parents=True, exist_ok=True)

    object_name = f"{_bucket_prefix()}/{filename}"
    destination = target_dir / filename
    payload = client.storage.from_(_bucket_name()).download(object_name)
    destination.write_bytes(payload)
    return str(destination)


def store_metadata(name: str, size: int, tier: str, details: dict | None = None):
    records = _load_local_index()
    payload = {
        "name": name,
        "size": int(size),
        "tier": tier,
        "created_at": _utc_now_iso(),
        "details": details or {},
    }
    records.append(payload)
    _save_local_index(records)
    return name


def list_metadata(limit: int = 500):
    client = _client()
    if client is None:
        return _load_local_index()[-limit:]

    try:
        # Try to list from Supabase with a short timeout
        rows = client.storage.from_(_bucket_name()).list(
            _bucket_prefix(),
            {"limit": int(limit), "offset": 0, "sortBy": {"column": "name", "order": "desc"}},
        )
    except (ConnectionError, TimeoutError, Exception):
        # Fall back to local index on any error
        return _load_local_index()[-limit:]

    result = []
    try:
        for item in rows or []:
            result.append(
                {
                    "id": item.get("id") or item.get("name"),
                    "name": item.get("name"),
                    "bucket_id": _bucket_name(),
                    "path": f"{_bucket_prefix()}/{item.get('name')}",
                    "metadata": item,
                }
            )
        return result
    except Exception:
        return _load_local_index()[-limit:]
    return result


def get_bucket_url() -> str:
    return _supabase_url()
