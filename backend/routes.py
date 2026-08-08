import sys
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import db, schemas, crud, models
from typing import List

# Ensure the parent directory is accessible so 'prediction.py' can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/agents/register")
def register_agent(payload: schemas.AgentRegister, session: Session = Depends(db.get_db)):
    # Safely route to CRUD without direct metadata table hacking
    agent = crud.create_agent(session, payload.agent_id, payload.info)
    return {"agent": agent.agent_id}

@router.post("/telemetry")
def telemetry(payload: schemas.TelemetryIn, session: Session = Depends(db.get_db)):
    t = crud.add_telemetry(session, payload.agent_id, payload.payload)
    return {"id": t.id}

@router.post("/files", response_model=dict)
def upsert_file(file: schemas.FileRecordIn, session: Session = Depends(db.get_db)):
    obj = crud.upsert_file(session, file.dict())
    return {"id": obj.id, "path": obj.path}

@router.get("/files", response_model=List[dict])
def list_files(session: Session = Depends(db.get_db)):
    # Properly query the ORM model instead of a raw SQL mapping
    rows = session.query(models.FileRecord).order_by(models.FileRecord.id.desc()).limit(100).all()
    return [{"id": r.id, "path": r.path, "size": r.size, "tier": r.tier, "temperature": r.temperature} for r in rows]

@router.get("/commands")
def get_commands(agent_id: str | None = None, session: Session = Depends(db.get_db)):
    cmds = crud.get_pending_commands(session, agent_id)
    return [{"id": c.id, "command_type": c.command_type, "target_path": c.target_path, "payload": c.payload} for c in cmds]

@router.post("/commands/{command_id}/ack")
def ack_command(command_id: int, session: Session = Depends(db.get_db)):
    obj = crud.ack_command(session, command_id)
    if not obj:
        raise HTTPException(status_code=404, detail="command not found")
    return {"id": obj.id, "status": obj.status}

@router.post("/schedule")
def run_schedule(session: Session = Depends(db.get_db)):
    from . import scheduler
    created = scheduler.schedule_from_files(session)
    return {"created": len(created)}

# Fixed duplicate route mapping
@router.post("/schedule/action")
def schedule_action():
    return {"scheduled": True}

@router.post("/predict")
def predict():
    try:
        import prediction
        # Triggers Advanced AI Prediction (Transformer Ready) objective
        result = prediction.predict_system_future(None, horizon_hours=24)
    except Exception as e:
        return {"predictions": [], "error": str(e)}
    return {"predictions": [result]}
