# scheduler/models.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, List


class Host(BaseModel):
    host_id: str
    hostname: Optional[str] = None
    status: Optional[str] = "UP"
    cpu_count: Optional[int] = 1
    cpu_percent: float
    mem_percent: float
    mem_free_bytes: Optional[int] = None
    load1: Optional[float] = 0.0
    last_seen_ts: Optional[int] = 0
    labels: Optional[Dict[str, Any]] = None
    # agent flags (optional)
    agent_flags: Optional[List[str]] = None


class VM(BaseModel):
    vm_uuid: str
    name: Optional[str] = None
    host_id: Optional[str] = None
    vcpus: Optional[int] = 1
    mem_bytes: Optional[int] = 0
    cpu_percent: Optional[float] = 0.0
    protected: Optional[bool] = False
    last_migrated_at: Optional[int] = None


class Alert(BaseModel):
    host_id: str
    level: str  # "orange" or "red"
    timestamp: int
    metrics: Dict[str, Any]
    recent_vms: Optional[List[Dict[str, Any]]] = None
