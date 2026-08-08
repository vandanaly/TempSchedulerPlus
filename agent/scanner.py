from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import time
import math
from typing import Iterable, Dict

try:
    import psutil
except ImportError:
    psutil = None

def _get_cpu_temp() -> float | None:
    if not psutil:
        return None
    try:
        # psutil.sensors_temperatures() is primarily for Linux/FreeBSD.
        # On Windows, we safely bypass this without crashing the agent.
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                for key in temps:
                    entries = temps[key]
                    if entries:
                        return float(entries[0].current)
        return None
    except Exception:
        return None

def scan_paths(root: Path | str, max_files: int = 500) -> Iterable[Dict]:
    """
    Scan `root` recursively and yield file metadata dicts.
    Formats data perfectly for Advanced AI Prediction (Transformer) ingestion.
    """
    root = Path(root)
    count = 0
    cpu_temp = _get_cpu_temp()
    
    # Establish a single reliable UNIX timestamp for the entire scan cycle
    now_ts = time.time()
    
    for p in root.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:
                continue
                
            last_accessed = datetime.fromtimestamp(st.st_atime, tz=timezone.utc).isoformat()
            size = st.st_size
            ext = p.suffix.lower().lstrip('.')
            
            # Robust age calculation using direct UNIX math
            age_seconds = max(0.0, now_ts - st.st_atime)
            
            # Initial base score. The backend's Auto Parameter Tuning will scale this.
            temp_score = 1.0 / (1.0 + math.log1p(age_seconds)) if age_seconds > 0 else 1.0
            
            yield {
                "path": str(p),
                "size": size,
                "last_accessed": last_accessed,
                "file_type": ext,
                "temperature_score": round(float(temp_score), 6),
                "cpu_temp": cpu_temp,
            }
            
            count += 1
            if count >= max_files:
                return
