from datetime import datetime, timezone
from pathlib import Path

import cloud_storage
import config
import prediction

from temperature import _load_store, _save_store, calculate_temperature, load_temperatures

temperature_store = {}

def _last_access_timestamp(path: Path) -> float:
    metadata = path.stat()
    return metadata.st_mtime if metadata.st_mtime else datetime.now(timezone.utc).timestamp()

def _get_adaptive_thresholds(store):
    """
    Auto Parameter Tuning & Real-Time Adaptive Scheduling.
    Automatically optimizes temperature thresholds based on real-time system load.
    """
    base_hot = getattr(config, "HOT_THRESHOLD_BASE", 600.0)
    base_warm = getattr(config, "WARM_THRESHOLD_BASE", 400.0)
    
    # Fallback to static if tuning is disabled or store is empty
    if not getattr(config, "AUTO_TUNE_ENABLED", False) or not store:
        return base_hot, base_warm
        
    temps = [v.get("temperature", 500.0) for v in store.values() if isinstance(v, dict)]
    if not temps:
        return base_hot, base_warm
        
    avg_temp = sum(temps) / len(temps)
    
    # Dynamically shift thresholds based on current system heat (load factor)
    load_factor = (avg_temp - 500.0) / 500.0
    
    dynamic_hot = max(400.0, min(750.0, base_hot + (load_factor * 100)))
    dynamic_warm = max(300.0, min(600.0, base_warm + (load_factor * 50)))
    
    return dynamic_hot, dynamic_warm

def classify_temperature(temp: float, hot_thresh: float, warm_thresh: float):
    if temp >= hot_thresh:
        return "HOT"
    if temp >= warm_thresh:
        return "WARM"
    return "COLD"

def _device_files():
    paths = [path for path in sorted(config.DEVICE.iterdir()) if path.is_file()]
    max_files = int(getattr(config, "SCHEDULER_MAX_FILES", 0) or 0)
    if max_files > 0:
        return paths[:max_files]
    return paths

def schedule():
    store = _load_store()
    actions = []
    paths = _device_files()
    
    # Calculate real-time dynamic thresholds
    hot_thresh, warm_thresh = _get_adaptive_thresholds(store)

    path_rows = []
    forecast_inputs = []
    for path in paths:
        metadata = path.stat()
        last_access = metadata.st_mtime if metadata.st_mtime else _last_access_timestamp(path)
        temp = calculate_temperature(
            str(path),
            last_access,
            metadata.st_size,
            store=store,
            persist=False,
        )
        temperature_store[path.name] = temp
        forecast_inputs.append(
            {
                "path": str(path),
                "size": int(metadata.st_size),
                "last_access": float(last_access),
                "last_modified": float(metadata.st_mtime),
                "session": "scheduler",
                "user": "local",
            }
        )
        path_rows.append((path, metadata, temp))

    _save_store(store)
    forecasts = prediction.predict_future_batch(forecast_inputs, horizon_hours=24)

    for (path, metadata, temp), forecast in zip(path_rows, forecasts):
        tier = classify_temperature(temp, hot_thresh, warm_thresh)
        if tier == "COLD":
            record = cloud_storage.archive_cold_file(path, temp)
            actions.append(
                {
                    "filename": path.name,
                    "tier": tier,
                    "target": "cloud",
                    "temperature": round(temp, 2),
                    "forecast_temperature": forecast.get("predicted_temperature"),
                    "forecast_tier": forecast.get("predicted_tier"),
                    "recommendation": forecast.get("recommendation"),
                    "record": record,
                }
            )
        elif tier == "WARM":
            destination = cloud_storage.move_to_edge(path, temp)
            actions.append(
                {
                    "filename": path.name,
                    "tier": tier,
                    "target": "edge",
                    "temperature": round(temp, 2),
                    "forecast_temperature": forecast.get("predicted_temperature"),
                    "forecast_tier": forecast.get("predicted_tier"),
                    "recommendation": forecast.get("recommendation"),
                    "record": {"path": str(destination)},
                }
            )
        else:
            actions.append(
                {
                    "filename": path.name,
                    "tier": tier,
                    "target": "device",
                    "temperature": round(temp, 2),
                    "forecast_temperature": forecast.get("predicted_temperature"),
                    "forecast_tier": forecast.get("predicted_tier"),
                    "recommendation": forecast.get("recommendation"),
                }
            )

    return actions

def snapshot():
    return {
        "device": [path.name for path in config.DEVICE.iterdir() if path.is_file()],
        "edge": [path.name for path in config.EDGE.iterdir() if path.is_file()],
        "cloud": [path.name for path in config.CLOUD.iterdir() if path.is_file() and path.name != "index.json"],
        "compressed": [path.name for path in config.COMPRESSED.iterdir() if path.is_file()],
        "encrypted": [path.name for path in config.ENCRYPTED.iterdir() if path.is_file()],
        "cloud_records": cloud_storage.get_cloud_records(),
        "temperature_store": load_temperatures(),
    }
