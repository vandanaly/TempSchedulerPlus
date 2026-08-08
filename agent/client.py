from __future__ import annotations

from typing import Any, Dict
import os
import httpx

class AgentClient:
    def __init__(self, backend_url: str | None = None, timeout: int = 15):
        # Dynamically hunt for the production API URL, fallback to localhost for dev
        env_url = os.environ.get("NEXT_PUBLIC_API_URL") or os.environ.get("TSPLUS_BACKEND_URL")
        self.backend = (backend_url or env_url or "http://127.0.0.1:8000").rstrip('/')
        self.session = httpx.Client(timeout=timeout)

    def register(self, agent_id: str, info: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.backend}/api/agents/register"
        payload = {"agent_id": agent_id, "info": info or {}}
        r = self.session.post(url, json=payload)
        r.raise_for_status()
        return r.json()

    def send_telemetry(self, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.backend}/api/telemetry"
        body = {"agent_id": agent_id, "payload": payload}
        r = self.session.post(url, json=body)
        r.raise_for_status()
        return r.json()
