from datetime import datetime
from pydantic import BaseModel
from typing import Any, Dict, Optional


class AgentRegister(BaseModel):
    agent_id: str
    info: Optional[Dict[str, Any]] = None


class TelemetryIn(BaseModel):
    agent_id: str
    payload: Dict[str, Any]


class FileRecordIn(BaseModel):
    path: str
    size: Optional[int]
    last_accessed: Optional[datetime]
    access_count: Optional[int] = 0
    temperature: Optional[float] = 0.0
    tier: Optional[str] = "device"
    metadata_json: Optional[Dict[str, Any]] = {}


class FileRecordOut(FileRecordIn):
    id: int
