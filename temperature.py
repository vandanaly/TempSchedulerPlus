import json
import time
from pathlib import Path

import config

TEMP_STORE_FILE = config.LOGS / "temperature_history.json"

MIN_TEMP = 300.0
MAX_TEMP = 800.0

def _load_store():
    if TEMP_STORE_FILE.exists():
        try:
            return json.loads(
                TEMP_STORE_FILE.read_text(encoding="utf-8")
            )
        except Exception:
            pass
    return {}

def _save_store(store):
    TEMP_STORE_FILE.write_text(
        json.dumps(store, indent=2),
        encoding="utf-8"
    )

def _clamp(value):
    return max(
        MIN_TEMP,
        min(MAX_TEMP, float(value))
    )

def calculate_temperature(path, last_access, size_bytes, store=None, persist=True):
    """
    Real file hotness calculation with Auto Parameter Tuning.
    Returns 300–800.
    """
    if store is None:
        store = _load_store()

    filename = Path(path).name
    now = time.time()

    days_since_access = max((now - float(last_access)) / 86400, 0)
    size_mb = float(size_bytes) / (1024 * 1024)

    # Recency component
    if days_since_access <= 1:
        recency_score = 1.0
    elif days_since_access <= 3:
        recency_score = 0.85
    elif days_since_access <= 7:
        recency_score = 0.70
    elif days_since_access <= 14:
        recency_score = 0.50
    elif days_since_access <= 30:
        recency_score = 0.30
    else:
        recency_score = 0.10

    # Auto Parameter Tuning: Dynamically scale the size penalty based on file category
    if size_mb > 1000:
        # Massive files penalize heavily to push to Cold Data Compression faster
        size_penalty_weight = 150.0 
    elif size_mb < 5:
        # Tiny files have almost no size penalty
        size_penalty_weight = 20.0
    else:
        size_penalty_weight = 100.0

    size_score = min(size_mb / 100.0, 1.0)

    current_temp = 300 + (recency_score * 400) + (size_score * size_penalty_weight)
    current_temp = _clamp(current_temp)

    previous = store.get(filename)
    if previous:
        current_temp = (previous["temperature"] * 0.30) + (current_temp * 0.70)

    current_temp = round(current_temp, 2)

    if filename not in store:
        store[filename] = {
            "temperature": current_temp,
            "last_access": float(last_access),
            "size": int(size_bytes),
            "updated": now,
            "history": []
        }

    if "history" not in store[filename]:
        store[filename]["history"] = []

    store[filename]["history"].append({
        "timestamp": now,
        "temperature": current_temp,
        "size": int(size_bytes),
        "days_since_access": round(days_since_access, 3)
    })

    store[filename]["history"] = store[filename]["history"][-50:]
    store[filename]["temperature"] = current_temp
    store[filename]["last_access"] = float(last_access)
    store[filename]["size"] = int(size_bytes)
    store[filename]["updated"] = now

    if persist:
        _save_store(store)

    return current_temp

def load_temperatures():
    return _load_store()