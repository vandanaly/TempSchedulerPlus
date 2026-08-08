from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
import json
import threading
import time

import torch
import torch.nn.functional as F

import config
from models.train_transformer import ensure_model
from models.transformer_encoder import (
    DEFAULT_MAX_SEQ_LEN,
    FileTemperatureTransformer,
    build_feature_vector,
)
MIN_TEMP = 300.0
MAX_TEMP = 800.0

_MODEL_LOCK = threading.Lock()
_MODEL: FileTemperatureTransformer | None = None
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _clamp_temperature(value: float) -> float:
    return max(MIN_TEMP, min(MAX_TEMP, float(value)))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _current_from_temperature_series(temperatures):
    if not temperatures:
        return 500.0

    values = [_safe_float(value, 500.0) for value in temperatures]
    if len(values) == 1:
        return _clamp_temperature(values[0])

    recent_values = values[-5:]
    recent_mean = mean(recent_values)
    latest = values[-1]
    current = (recent_mean * 0.4) + (latest * 0.6)
    return _clamp_temperature(current)


def _estimate_from_file_info(file_info):
    last_access = _safe_float(file_info.get("last_access", 0.0), 0.0)
    last_modified = _safe_float(file_info.get("last_modified", last_access), last_access)
    size = _safe_float(file_info.get("size", 0.0), 0.0)
    now = time.time()

    days_since_access = max((now - last_access) / 86400.0, 0.0)
    size_mb = size / (1024.0 * 1024.0)

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

    size_score = min(size_mb / 100.0, 1.0)
    return _clamp_temperature(300.0 + (recency_score * 400.0) + (size_score * 100.0))


def _tier_from_temperature(temperature: float) -> str:
    if temperature >= float(config.HOT_THRESHOLD):
        return "HOT"
    if temperature >= float(config.WARM_THRESHOLD):
        return "WARM"
    return "COLD"


def _recommendation_for_tier(tier: str) -> str:
    normalized = str(tier).upper()
    if normalized == "HOT":
        return "Keep on device tier for low-latency access."
    if normalized == "WARM":
        return "Move to edge tier and monitor access bursts."
    return "Archive to cloud tier with compression and encryption."


def _utc_epoch_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_timestamp(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _load_temperature_store() -> dict:
    store_path = Path(config.LOGS) / "temperature_history.json"
    if not store_path.exists():
        return {}
    try:
        return json.loads(store_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_recent_events(limit: int = 500) -> list[dict]:
    events = []

    action_log = Path(config.LOGS) / "actions.jsonl"
    if action_log.exists():
        try:
            for line in action_log.read_text(encoding="utf-8").splitlines()[-300:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(
                    {
                        "timestamp": _parse_timestamp(payload.get("timestamp")),
                        "filename": payload.get("filename", ""),
                        "path": payload.get("filename", ""),
                        "size": _safe_float(payload.get("details", {}).get("size_bytes", 0), 0.0),
                        "temperature": _safe_float(payload.get("temperature", 500.0), 500.0),
                    }
                )
        except OSError:
            pass

    manifest_path = Path(config.LOGS) / "cold_pipeline_manifest.json"
    if manifest_path.exists():
        try:
            rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            rows = []
        for item in rows[-300:]:
            events.append(
                {
                    "timestamp": _parse_timestamp(item.get("timestamp")),
                    "filename": Path(item.get("original_path", "")).name,
                    "path": item.get("original_path", ""),
                    "size": _safe_float(item.get("size", 0.0), 0.0),
                    "temperature": _safe_float(item.get("predicted_temperature", 500.0), 500.0),
                }
            )

    events.sort(key=lambda item: item.get("timestamp", 0.0))
    return events[-limit:]


def _get_model() -> FileTemperatureTransformer:
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            _MODEL = ensure_model(_DEVICE)
        return _MODEL


@dataclass
class PredictionResult:
    predicted_temperature: float
    predicted_tier: str
    recommendation: str
    confidence: float
    horizon_hours: int

    def to_dict(self):
        return {
            "predicted_temperature": round(float(self.predicted_temperature), 2),
            "predicted_tier": self.predicted_tier,
            "recommendation": self.recommendation,
            "confidence": round(float(self.confidence), 3),
            "horizon_hours": int(self.horizon_hours),
        }


class PyTorchTransformerPredictionEngine:
    """Real PyTorch TransformerEncoder for per-file and system temperature forecasting."""

    def _build_file_sequence(self, file_info: dict, horizon_hours: int) -> tuple[list[list[float]], str]:
        now_ts = _utc_epoch_now()
        file_path = str(file_info.get("path", ""))
        filename = Path(file_path).name if file_path else ""
        store = _load_temperature_store()
        record = store.get(filename, {})
        history = sorted(record.get("history") or [], key=lambda item: float(item.get("timestamp", 0.0)))

        sequence = []
        for item in history[-DEFAULT_MAX_SEQ_LEN :]:
            timestamp = float(item.get("timestamp", now_ts))
            days = float(item.get("days_since_access", 0.0))
            sequence.append(
                build_feature_vector(
                    timestamp=timestamp,
                    temperature=float(item.get("temperature", record.get("temperature", 500.0))),
                    size_bytes=float(item.get("size", record.get("size", file_info.get("size", 0.0)))),
                    days_since_access=days,
                    path=file_path or filename,
                    horizon_hours=horizon_hours,
                )
            )

        events = _load_recent_events()
        for event in events:
            event_name = str(event.get("filename", "")).lower()
            if filename and event_name != filename.lower():
                continue
            timestamp = float(event.get("timestamp", now_ts))
            days = max((now_ts - timestamp) / 86400.0, 0.0)
            sequence.append(
                build_feature_vector(
                    timestamp=timestamp,
                    temperature=float(event.get("temperature", record.get("temperature", 500.0))),
                    size_bytes=float(event.get("size", file_info.get("size", 0.0))),
                    days_since_access=days,
                    path=file_path or event.get("path", filename),
                    horizon_hours=horizon_hours,
                )
            )

        last_access = _safe_float(file_info.get("last_access", now_ts), now_ts)
        size = _safe_float(file_info.get("size", record.get("size", 0.0)), 0.0)
        current_temp = float(record.get("temperature", _estimate_from_file_info(file_info)))
        days_since_access = max((now_ts - last_access) / 86400.0, 0.0)
        sequence.append(
            build_feature_vector(
                timestamp=now_ts,
                temperature=current_temp,
                size_bytes=size,
                days_since_access=days_since_access,
                path=file_path or filename or "unknown",
                horizon_hours=horizon_hours,
            )
        )

        return sequence[-DEFAULT_MAX_SEQ_LEN :], file_path or filename or "unknown"

    def _build_system_sequence(self, temperature_store, horizon_hours: int) -> tuple[list[list[float]], str]:
        now_ts = _utc_epoch_now()
        points = []

        if isinstance(temperature_store, dict):
            for name, record in temperature_store.items():
                for item in record.get("history") or []:
                    points.append(
                        (
                            float(item.get("timestamp", now_ts)),
                            float(item.get("temperature", record.get("temperature", 500.0))),
                            float(item.get("size", record.get("size", 0.0))),
                            float(item.get("days_since_access", 0.0)),
                            str(name),
                        )
                    )
                points.append(
                    (
                        float(record.get("updated", now_ts)),
                        float(record.get("temperature", 500.0)),
                        float(record.get("size", 0.0)),
                        max((now_ts - float(record.get("last_access", now_ts))) / 86400.0, 0.0),
                        str(name),
                    )
                )
        else:
            for index, value in enumerate(list(temperature_store or [])[-DEFAULT_MAX_SEQ_LEN :]):
                points.append((now_ts - (len(temperature_store) - index) * 3600.0, float(value), 0.0, 0.0, "system"))

        if not points:
            baseline = _estimate_from_file_info(
                {
                    "last_access": now_ts,
                    "last_modified": now_ts,
                    "size": 1024.0,
                }
            )
            return [
                build_feature_vector(
                    timestamp=now_ts,
                    temperature=baseline,
                    size_bytes=1024.0,
                    days_since_access=0.0,
                    path="system://aggregate",
                    horizon_hours=horizon_hours,
                )
            ], "system://aggregate"

        points.sort(key=lambda item: item[0])
        bucketed: dict[int, list[tuple]] = {}
        for timestamp, temperature, size, days, name in points:
            bucket = int(timestamp // 3600)
            bucketed.setdefault(bucket, []).append((temperature, size, days, name))

        sequence = []
        for bucket in sorted(bucketed.keys())[-DEFAULT_MAX_SEQ_LEN :]:
            rows = bucketed[bucket]
            avg_temp = mean(row[0] for row in rows)
            avg_size = mean(row[1] for row in rows)
            avg_days = mean(row[2] for row in rows)
            sample_name = rows[-1][3]
            sequence.append(
                build_feature_vector(
                    timestamp=float(bucket * 3600),
                    temperature=float(avg_temp),
                    size_bytes=float(avg_size),
                    days_since_access=float(avg_days),
                    path=f"system://{sample_name}",
                    horizon_hours=horizon_hours,
                )
            )

        return sequence, "system://aggregate"

    def _predict_batch(self, sequences: list[tuple[list[list[float]], str]]) -> list[PredictionResult]:
        if not sequences:
            return []

        model = _get_model()
        batch = FileTemperatureTransformer.pack_sequences(sequences, _DEVICE)
        with torch.inference_mode():
            temp_norm, tier_logits, _confidence = model(batch)
            tier_probs = F.softmax(tier_logits, dim=-1)
            tier_confidence = tier_probs.max(dim=-1).values
            history_confidence = (batch.lengths.float() / float(DEFAULT_MAX_SEQ_LEN)).clamp(0.0, 1.0)

        results = []
        for index in range(len(sequences)):
            predicted_temperature = FileTemperatureTransformer.denormalize_temperature(temp_norm[index])
            predicted_tier = FileTemperatureTransformer.tier_from_logits(tier_logits[index])
            conf = float(
                (tier_confidence[index] * 0.70 + history_confidence[index] * 0.30).clamp(0.35, 0.99).item()
            )
            results.append(
                PredictionResult(
                    predicted_temperature=round(predicted_temperature, 2),
                    predicted_tier=predicted_tier,
                    recommendation=_recommendation_for_tier(predicted_tier),
                    confidence=conf,
                    horizon_hours=24,
                )
            )
        return results

    def predict(self, file_info=None, horizon_hours: int = 24) -> PredictionResult:
        file_info = file_info or {}
        sequence, path = self._build_file_sequence(file_info, horizon_hours=int(horizon_hours))
        result = self._predict_batch([(sequence, path)])[0]
        result.horizon_hours = int(horizon_hours)
        return result

    def predict_many(self, file_infos: list[dict], horizon_hours: int = 24) -> list[PredictionResult]:
        sequences = [self._build_file_sequence(info, horizon_hours=int(horizon_hours)) for info in file_infos]
        results = self._predict_batch(sequences)
        for result in results:
            result.horizon_hours = int(horizon_hours)
        return results

    def predict_system(self, temperature_store=None, horizon_hours: int = 24) -> PredictionResult:
        sequence, path = self._build_system_sequence(temperature_store, horizon_hours=int(horizon_hours))
        result = self._predict_batch([(sequence, path)])[0]
        result.horizon_hours = int(horizon_hours)
        return result


_ENGINE = PyTorchTransformerPredictionEngine()


def current_temperature(temperatures=None):
    """Estimate current temperature from observed values or file-level features."""
    if temperatures is None:
        return 500.0

    if isinstance(temperatures, dict):
        if {"last_access", "last_modified", "size"}.issubset(temperatures.keys()):
            return round(_estimate_from_file_info(temperatures), 2)
        temperatures = [item.get("temperature", item) for item in temperatures.values()]

    return round(_current_from_temperature_series(list(temperatures)), 2)


def predict_future(file_info=None, horizon_hours: int = 24):
    """Predict future tier temperature and migration recommendation for a file descriptor."""
    return _ENGINE.predict(file_info=file_info or {}, horizon_hours=horizon_hours).to_dict()


def predict_future_batch(file_infos, horizon_hours: int = 24):
    """Batch prediction helper for scheduler and scan pipelines."""
    if not file_infos:
        return []
    return [result.to_dict() for result in _ENGINE.predict_many(file_infos, horizon_hours=horizon_hours)]


def predict_system_future(temperature_store=None, horizon_hours: int = 24):
    """Predict next system temperature window based on thermal history."""
    if isinstance(temperature_store, list):
        current = current_temperature(temperature_store)
        store_payload = None
    else:
        store_payload = temperature_store if isinstance(temperature_store, dict) else _load_temperature_store()
        current = current_temperature(store_payload)

    prediction = _ENGINE.predict_system(store_payload or temperature_store, horizon_hours=horizon_hours)
    blended = _clamp_temperature((float(prediction.predicted_temperature) * 0.65) + (float(current) * 0.35))
    tier = _tier_from_temperature(blended)
    return {
        "current_temperature": round(float(current), 2),
        "predicted_temperature": round(float(blended), 2),
        "predicted_tier": tier,
        "recommendation": _recommendation_for_tier(tier),
        "confidence": round(float(prediction.confidence), 3),
        "horizon_hours": int(horizon_hours),
    }


def predict(temperatures=None):
    """Backward-compatible numeric predictor used by the cold pipeline."""
    if isinstance(temperatures, dict) and {"last_access", "last_modified", "size"}.issubset(temperatures.keys()):
        return float(predict_future(temperatures).get("predicted_temperature", current_temperature(temperatures)))
    return current_temperature(temperatures)
