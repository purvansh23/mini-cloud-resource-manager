from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from app.db import get_db
from app import models
import time

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class MetricsSchema(BaseModel):
    host_name: str
    cpu_percent: float
    mem_percent: float
    vms_running: int


@router.post("/report")
def report_metrics(payload: MetricsSchema, db: Session = Depends(get_db)):

    # Find host
    host = db.query(models.Host).filter(models.Host.name == payload.host_name).first()

    # If host does not exist, create it
    if not host:
        host = models.Host(name=payload.host_name, ip=None)
        db.add(host)
        db.commit()
        db.refresh(host)

    # Insert metric entry
    metric = models.HostMetric(
        host_id=host.id,
        cpu_percent=payload.cpu_percent,
        mem_percent=payload.mem_percent,
        vms_running=payload.vms_running,
        ts=int(time.time())
    )

    db.add(metric)
    db.commit()

    return {"status": "ok"}
