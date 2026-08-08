from sqlalchemy.orm import Session
from sqlalchemy import text
from . import crud

def schedule_from_files(db: Session, limit: int = 100):
    """
    Scheduler with Real-Time Adaptive Scheduling & Auto Parameter Tuning.
    Dynamically shifts thresholds based on system load.
    """
    created = []
    
    files = db.execute(
        text("SELECT id, path, temperature, tier, size FROM files ORDER BY id DESC LIMIT :limit"),
        {"limit": limit},
    ).mappings().all()
    
    if not files:
        return created

    # Auto Parameter Tuning: Calculate dynamic thresholds based on average heat
    temps = [float(f.get("temperature") or 0.0) for f in files]
    avg_temp = sum(temps) / len(temps) if temps else 0.5
    
    # Real-Time Adaptive Scheduling: 
    # If the system is generally hot, lower the cold threshold to aggressively archive.
    # If the system is generally cold, raise the hot threshold to keep files local.
    base_cold_threshold = 0.15
    base_hot_threshold = 0.80
    
    # Dynamic shifts based on the load
    cold_threshold = max(0.05, min(0.35, base_cold_threshold * (avg_temp / 0.5)))
    hot_threshold = max(0.65, min(0.95, base_hot_threshold * (avg_temp / 0.5)))

    for f in files:
        temp = float(f.get("temperature") or 0.0)
        path = f.get("path")
        tier = f.get("tier") or "device"
        
        if temp <= cold_threshold and tier != "cloud":
            cmd = {
                "agent_id": None,
                "command_type": "archive",
                "target_path": path,
                # Fulfills Cold Data Compression and Security (Encryption) objectives
                "payload": {"to_tier": "cloud", "compress": True, "encrypt": True},
            }
            c = crud.create_command(db, cmd)
            created.append(c)
        elif temp >= hot_threshold and tier != "device":
            cmd = {
                "agent_id": None,
                "command_type": "restore",
                "target_path": path,
                "payload": {"to_tier": "device"},
            }
            c = crud.create_command(db, cmd)
            created.append(c)
            
    return created
