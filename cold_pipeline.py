from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import time

import config
import prediction


MANIFEST_PATH = config.LOGS / "cold_pipeline_manifest.json"


def _scan_paths_from_config():
    default_paths = [Path.home() / "Documents", Path.home() / "Downloads"]
    return getattr(config, "SCAN_PATHS", default_paths)


def _scan_max_files_from_config():
    return int(getattr(config, "SCAN_MAX_FILES", 1500))


def _scan_min_size_from_config():
    return int(getattr(config, "SCAN_MIN_SIZE_BYTES", 4096))


def _skip_extensions_from_config():
    return set(getattr(config, "SKIP_EXTENSIONS", {".exe", ".dll", ".sys", ".tmp", ".cache"}))


def _skip_dirs_from_config():
    """Directories to skip during scanning to speed up traversal"""
    return set(getattr(config, "SKIP_DIRS", {
        ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
        ".vscode", ".idea", "dist", "build", "*.egg-info", ".env"
    }))


def _max_scan_depth():
    """Limit directory traversal depth to avoid scanning too deep"""
    return int(getattr(config, "SCAN_MAX_DEPTH", 4))


def should_skip(file_path: Path):
    return file_path.suffix.lower() in _skip_extensions_from_config()


def _safe_stat(file_path: Path):
    try:
        return file_path.stat()
    except (PermissionError, FileNotFoundError, OSError):
        return None


def _load_manifest():
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def _save_manifest(records):
    MANIFEST_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _device_stage_path(source_path: Path):
    source_hash = str(abs(hash(str(source_path.resolve()))))
    return config.DEVICE / f"stage_{source_hash}_{source_path.name}"


def _edge_stage_path(source_path: Path):
    source_hash = str(abs(hash(str(source_path.resolve()))))
    return config.EDGE / f"stage_{source_hash}_{source_path.name}"


def _cloud_stage_pattern(source_path: Path):
    source_hash = str(abs(hash(str(source_path.resolve()))))
    return f"stage_{source_hash}_{source_path.stem}.bundle.enc"


def _is_present_in_any_tier(source_path: Path):
    if _device_stage_path(source_path).exists():
        return True
    if _edge_stage_path(source_path).exists():
        return True
    if (config.CLOUD / _cloud_stage_pattern(source_path)).exists():
        return True
    return False


def _max_stage_size():
    """Skip staging files larger than this (in bytes) to speed up"""
    return int(getattr(config, "SCAN_MAX_STAGE_BYTES", 500 * 1024 * 1024))  # 500MB default


def stage_to_device(source_path: Path):
    """Skip staging if file is too large"""
    # Don't stage files larger than max size
    try:
        if source_path.stat().st_size > _max_stage_size():
            return None
    except (OSError, PermissionError):
        return None
    
    staged_path = _device_stage_path(source_path)
    staged_path.parent.mkdir(parents=True, exist_ok=True)
    if not staged_path.exists():
        try:
            shutil.copy2(source_path, staged_path)
        except (OSError, PermissionError, IOError):
            return None
    return staged_path


def get_files(scan_paths=None, max_files=None):
    selected_paths = scan_paths or _scan_paths_from_config()
    limit = max_files or _scan_max_files_from_config()
    skip_dirs = _skip_dirs_from_config()
    max_depth = _max_scan_depth()

    file_data = []
    for root_path in selected_paths:
        root = Path(root_path)
        if not root.exists() or not root.is_dir():
            continue

        for current_root, dirs, files in os.walk(root):
            # Calculate depth
            depth = len(Path(current_root).relative_to(root).parts)
            if depth > max_depth:
                dirs.clear()  # Don't descend further
                continue

            # Skip known slow/irrelevant directories
            dirs[:] = [d for d in dirs if d not in skip_dirs]

            for filename in files:
                path = Path(current_root) / filename
                if should_skip(path):
                    continue

                stats = _safe_stat(path)
                if stats is None:
                    continue
                if stats.st_size < _scan_min_size_from_config():
                    continue

                file_data.append(
                    {
                        "path": str(path),
                        "size": int(stats.st_size),
                        "last_access": float(stats.st_atime),
                        "last_modified": float(stats.st_mtime),
                    }
                )

                if len(file_data) >= limit:
                    return file_data

    return file_data


def classify_file(file_info):
    current_time = time.time()
    last_access_days = (current_time - float(file_info["last_access"])) / (60 * 60 * 24)

    if last_access_days < 2:
        return "hot"
    if last_access_days < 7:
        return "warm"
    return "cold"


def _decision_from_forecast(file_info, forecast):
    rule_decision = classify_file(file_info)
    raw_prediction = float(forecast.get("predicted_temperature", 500.0))
    ai_tier = str(forecast.get("predicted_tier", "WARM")).lower()
    if ai_tier == "hot":
        ai_decision = "hot"
    elif ai_tier == "cold":
        ai_decision = "cold"
    else:
        ai_decision = "warm"

    if rule_decision == "cold" and ai_decision == "cold":
        decision = "cold"
    elif rule_decision == "hot" or ai_decision == "hot":
        decision = "hot"
    else:
        decision = "warm"

    return decision, rule_decision, ai_decision, raw_prediction


def final_decision(file_info):
    try:
        forecast = prediction.predict_future(file_info, horizon_hours=24)
    except Exception:
        forecast = {
            "predicted_temperature": prediction.predict(file_info),
            "predicted_tier": "WARM",
        }
    return _decision_from_forecast(file_info, forecast)


def process_files(scan_paths=None, max_files=None):
    records = _load_manifest()
    processed_paths = {entry.get("original_path") for entry in records}

    files = get_files(scan_paths=scan_paths, max_files=max_files)
    cycle = {
        "scanned": len(files),
        "hot": 0,
        "warm": 0,
        "cold": 0,
        "staged": 0,
        "entries": [],
        "classified": [],
        "hot_files": [],
    }

    forecasts = prediction.predict_future_batch(files, horizon_hours=24)

    for file_info, forecast in zip(files, forecasts):
        decision, rule_decision, ai_decision, raw_prediction = _decision_from_forecast(file_info, forecast)
        cycle[decision] += 1

        path = Path(file_info["path"])
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "original_path": str(path),
            "size": file_info["size"],
            "decision": decision,
            "rule_decision": rule_decision,
            "ai_decision": ai_decision,
            "predicted_temperature": raw_prediction,
        }

        cycle["classified"].append(
            {
                "path": str(path),
                "size": file_info["size"],
                "decision": decision,
                "rule_decision": rule_decision,
                "ai_decision": ai_decision,
                "predicted_temperature": raw_prediction,
            }
        )
        if decision == "hot":
            cycle["hot_files"].append(str(path))

        # Only stage cold files (not hot/warm) and only if not processed
        should_stage = decision == "cold" and str(path) not in processed_paths and not _is_present_in_any_tier(path)
        if should_stage:
            try:
                staged_path = stage_to_device(path)
                if staged_path is None:
                    # Skip if staging failed (e.g., file too large)
                    continue
            except (FileNotFoundError, PermissionError, OSError):
                continue

            entry.update(
                {
                    "staged_path": str(staged_path),
                    "staged_tier": "device",
                }
            )
            records.append(entry)
            processed_paths.add(str(path))

            cycle["staged"] += 1
            cycle["entries"].append(entry)

    _save_manifest(records)

    # Keep payload bounded for UI/session storage - be more aggressive
    cycle["classified"] = cycle["classified"][:100]
    cycle["hot_files"] = cycle["hot_files"][:20]
    cycle["entries"] = cycle["entries"][:50]
    return cycle


def get_pipeline_stats():
    records = _load_manifest()
    total_staged = sum(int(item.get("size", 0)) for item in records)
    return {
        "compressed_records": len(records),
        "saved_bytes": total_staged,
        "saved_mb": round(total_staged / (1024 * 1024), 2),
        "recent": records[-10:],
    }