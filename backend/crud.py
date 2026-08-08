from sqlalchemy.orm import Session
from . import models as _models


def create_agent(db: Session, agent_id: str, info: dict | None = None):
    obj = _models.Agent(agent_id=agent_id, info=info or {})
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def upsert_file(db: Session, file_in: dict):
    obj = db.query(_models.FileRecord).filter_by(path=file_in["path"]).first()
    if obj:
        for k, v in file_in.items():
            setattr(obj, k, v)
    else:
        obj = _models.FileRecord(**file_in)
        db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def add_telemetry(db: Session, agent_id: str, payload: dict):
    t = _models.Telemetry(agent_id=agent_id, payload=payload)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def create_command(db: Session, command: dict):
    obj = _models.Command(**command)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def get_pending_commands(db: Session, agent_id: str | None = None):
    q = db.query(_models.Command).filter(_models.Command.status == 'pending')
    if agent_id:
        q = q.filter(_models.Command.agent_id.in_([agent_id, None]))
    return q.order_by(_models.Command.created_at.asc()).all()


def ack_command(db: Session, command_id: int):
    obj = db.query(_models.Command).filter_by(id=command_id).first()
    if not obj:
        return None
    obj.status = 'done'
    db.commit()
    db.refresh(obj)
    return obj
