# app/schemas.py
from pydantic import BaseModel
from typing import Optional, Dict, Any
from uuid import UUID

class HostRegister(BaseModel):
    id: UUID                         # real XCP-NG / Xen host UUID
    name: str
    ip: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class MetricsReport(BaseModel):
    host_name: str
    cpu_percent: float
    mem_percent: float
    load_avg: float
    vms_running: int

class VMCreate(BaseModel):
    name: str
    template_name: Optional[str] = None
    vcpu: Optional[int] = 1
    memory_mb: Optional[int] = 512
