# app/crud.py
from sqlalchemy.orm import Session
from app import models
from typing import Optional

def get_host_by_name(db: Session, name: str) -> Optional[models.Host]:
    return db.query(models.Host).filter(models.Host.name == name).first()

def create_host(db: Session, name: str, ip: str = None, metadata: dict = None) -> models.Host:
    host = models.Host(name=name, ip=ip, metadata_json=metadata)
    db.add(host)
    db.commit()
    db.refresh(host)
    return host

def get_or_create_host_by_name(db: Session, name: str, ip: str = None, metadata: dict = None) -> models.Host:
    host = get_host_by_name(db, name)
    if not host:
        host = create_host(db, name, ip, metadata)
    return host

def create_host_metric(db: Session, host_id, cpu, mem, load_avg, vms_running):
    metric = models.HostMetric(host_id=host_id, cpu_percent=cpu, mem_percent=mem, load_avg=load_avg, vms_running=vms_running)
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric

def list_vms(db: Session):
    return db.query(models.VM).all()

def create_job(db: Session, job_type: str, payload: dict):
    job = models.Job(type=job_type, payload=payload, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

def update_job_status(db: Session, job_id, status: str, result: dict = None):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        return None
    job.status = status
    if result is not None:
        job.result = result
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
