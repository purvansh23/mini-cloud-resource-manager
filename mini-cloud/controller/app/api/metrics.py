# app/api/metrics.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app import crud, schemas

router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.post("/report")
def report_metrics(payload: schemas.MetricsReport, db: Session = Depends(get_db)):
    host = crud.get_or_create_host_by_name(db, payload.host_name)
    metric = crud.create_host_metric(db, host.id, payload.cpu_percent, payload.mem_percent, payload.load_avg, payload.vms_running)
    return {"status": "ok", "metric_id": metric.id}
