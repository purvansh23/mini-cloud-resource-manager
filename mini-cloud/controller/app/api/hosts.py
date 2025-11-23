# app/api/hosts.py  (snippet)
from fastapi import APIRouter, Depends, HTTPException, Header
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import os

from app.db import get_db
from app import crud, schemas
from app.models import Host, HostMetric, VM

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.post("/register")
def register_host(payload: schemas.HostRegister, db: Session = Depends(get_db)):
    """
    Register or update a host using the real XCP-NG host UUID (payload.id).
    """
    # attempt to find an existing host by the supplied real UUID
    host = db.query(Host).filter(Host.id == payload.id).first()

    if host is None:
        # create new Host using the real xen UUID (payload.id)
        host = Host(
            id=payload.id,
            name=payload.name,
            ip=payload.ip,
            metadata_json=payload.metadata,
        )
        db.add(host)
    else:
        # update mutable fields
        host.name = payload.name
        host.ip = payload.ip
        host.metadata_json = payload.metadata

    db.commit()
    db.refresh(host)
    return {"status": "ok", "host_id": str(host.id)}

def require_controller_token(authorization: Optional[str] = Header(None)):
    expected = os.getenv("CONTROLLER_TOKEN")
    if expected:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != expected:
            raise HTTPException(status_code=401, detail="Invalid token")
    return True

@router.get("", response_model=List[Dict[str, Any]])
def get_hosts(session: Session = Depends(get_db), authorized: bool = Depends(require_controller_token)):
    """
    Return list of hosts with latest metrics for Scheduler.
    Endpoint: GET /hosts
    """
    hosts = session.query(Host).all()
    results: List[Dict[str, Any]] = []

    for h in hosts:
        metric = (
            session.query(HostMetric)
            .filter(HostMetric.host_id == h.id)
            .order_by(desc(HostMetric.ts))
            .first()
        )

        vm_count = session.query(func.count(VM.id)).filter(VM.host_id == h.id).scalar() or 0

        cpu_p = float(metric.cpu_percent) if metric and metric.cpu_percent is not None else 0.0
        mem_p = float(metric.mem_percent) if metric and metric.mem_percent is not None else 0.0
        load_1 = float(metric.load_avg) if metric and metric.load_avg is not None else 0.0
        host_obj = {
            "host_id": str(h.id),
            "hostname": h.name,
            "status": "UP",
            "cpu_count": None,
            "cpu_percent": cpu_p,
            "mem_percent": mem_p,
            "mem_free_bytes": None,
            "load1": load_1,
            "last_seen_ts": int(h.last_seen.timestamp()) if h.last_seen else None,
            "labels": h.metadata_json or {},
            "throttle_until": None,
            "vms_running": int(vm_count),
            "ip": h.ip,
        }
        results.append(host_obj)

    return results

