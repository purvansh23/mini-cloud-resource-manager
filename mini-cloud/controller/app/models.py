# app/models.py
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy.orm import relationship
from app.db import Base

class Host(Base):
    __tablename__ = "hosts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True, unique=True)
    ip = Column(String, nullable=True)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    metadata_json = Column("metadata", JSON, nullable=True)

    metrics = relationship("HostMetric", back_populates="host")

class HostMetric(Base):
    __tablename__ = "host_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(UUID(as_uuid=True), ForeignKey("hosts.id"), nullable=False)
    cpu_percent = Column(Float)
    mem_percent = Column(Float)
    load_avg = Column(Float)
    vms_running = Column(Integer)
    ts = Column(DateTime(timezone=True), server_default=func.now())

    host = relationship("Host", back_populates="metrics")

class VM(Base):
    __tablename__ = "vms"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    xen_uuid = Column(String, nullable=True, index=True)
    host_id = Column(UUID(as_uuid=True), ForeignKey("hosts.id"), nullable=True)
    vcpu = Column(Integer, default=1)
    memory_mb = Column(Integer, default=512)
    state = Column(String, default="stopped")
    ip = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Job(Base):
    __tablename__ = "jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String, nullable=False)
    status = Column(String, default="pending")
    payload = Column(JSON)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    level = Column(String, default="info")
    message = Column(String)
    metadata_json = Column("metadata", JSON, nullable=True)
    ts = Column(DateTime(timezone=True), server_default=func.now())


# -----------------------
# Migration models below
# -----------------------

class Migration(Base):
    __tablename__ = "migrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vm_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_host = Column(String, nullable=False)
    target_host = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    client_request_id = Column(String, nullable=True, index=True)

    status = Column(String, nullable=False, default="queued")  # queued, validating, running, finalizing, completed, failed, cancelled
    progress = Column(Integer, default=0)

    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)

    details = Column(JSON, nullable=True)

    # Relationship to events for convenience
    events = relationship("MigrationEvent", back_populates="migration", cascade="all, delete-orphan")

class MigrationEvent(Base):
    __tablename__ = "migration_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    migration_id = Column(UUID(as_uuid=True), ForeignKey("migrations.id"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    level = Column(String, nullable=False)
    message = Column(String, nullable=False)
    meta = Column(JSON, nullable=True)

    migration = relationship("Migration", back_populates="events")
