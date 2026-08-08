from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.sql import func
from .db import Base


class FileRecord(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True, nullable=False)
    size = Column(Integer)
    last_accessed = Column(DateTime)
    access_count = Column(Integer, default=0)
    temperature = Column(Float, default=0.0)
    tier = Column(String, default="device")
    metadata_json = Column(JSON, default={})


class Telemetry(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    payload = Column(JSON)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())
    info = Column(JSON)


class Command(Base):
    __tablename__ = "commands"
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=True)
    command_type = Column(String, nullable=False)
    target_path = Column(String, nullable=True)
    payload = Column(JSON, default={})
    status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
