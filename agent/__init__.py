"""Agent package for TempSchedPlus - scans files and sends telemetry to backend."""

from .scanner import scan_paths
from .client import AgentClient

__all__ = ["scan_paths", "AgentClient"]
