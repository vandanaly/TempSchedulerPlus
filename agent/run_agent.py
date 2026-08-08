"""Simple CLI to run the TempSchedPlus agent scanner and send telemetry."""

from __future__ import annotations

import argparse
from pathlib import Path
import time
from .scanner import scan_paths
from .client import AgentClient

def main():
    parser = argparse.ArgumentParser(prog="tempsched-agent")
    parser.add_argument("--backend", help="Backend base URL", default=None)
    parser.add_argument("--agent-id", help="Agent identifier", default=None)
    parser.add_argument("--path", help="Path to scan", default='.')
    parser.add_argument("--max-files", help="Max files to scan", type=int, default=200)
    args = parser.parse_args()

    agent_id = args.agent_id or ("agent-local-" + str(int(time.time())))
    client = AgentClient(args.backend)
    
    try:
        client.register(agent_id, info={"root": args.path, "purpose": "telemetry_collection"})
        print(f"Registered agent '{agent_id}' successfully.")
    except Exception as exc:
        print("Warning: failed to register agent (check backend URL/connection):", exc)

    print(f"Scanning up to {args.max_files} files in '{args.path}'...")
    records = list(scan_paths(Path(args.path), max_files=args.max_files))
    
    payload = {
        "scan_timestamp": int(time.time()), 
        "records": records,
        "metrics": {
            "scanned_count": len(records),
            "agent_status": "active"
        }
    }
    
    try:
        resp = client.send_telemetry(agent_id, payload)
        print("Telemetry sent successfully:", resp)
    except Exception as exc:
        print("Failed to send telemetry:", exc)

if __name__ == "__main__":
    main()
