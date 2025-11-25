from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import time

Base = declarative_base()

class Host(Base):
    __tablename__ = "hosts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    uuid_xen = Column(String, unique=True, nullable=True)
    ip = Column(String, nullable=True)

    metrics = relationship(
        "HostMetric",
        back_populates="host",
        cascade="all, delete-orphan"
    )

    vms = relationship(
        "VM",
        back_populates="host",
        cascade="all, delete-orphan"
    )


class HostMetric(Base):
    __tablename__ = "host_metrics"

    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"), nullable=False)

    cpu_percent = Column(Float, default=0.0)
    mem_percent = Column(Float, default=0.0)
    vms_running = Column(Integer, default=0)

    ts = Column(Integer, default=lambda: int(time.time()))

    host = relationship("Host", back_populates="metrics")


class VM(Base):
    __tablename__ = "vms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    uuid = Column(String, unique=True, nullable=True)

    host_id = Column(Integer, ForeignKey("hosts.id"))
    host = relationship("Host", back_populates="vms")

    ip = Column(String, nullable=True)
    memory_mb = Column(Integer, default=0)
    vcpus = Column(Integer, default=1)

    created_at = Column(Integer, default=lambda: int(time.time()))


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)
    payload = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(Integer, default=lambda: int(time.time()))
