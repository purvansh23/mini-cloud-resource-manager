# app/migration/api.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from sqlalchemy.orm import Session
from app import db
from app.models import Migration, VM

router = APIRouter(prefix="/migrations", tags=["migrations"])


class MigrationCreate(BaseModel):
    # accept either controller vm_id OR xen vm_uuid (one of them required)
    vm_id: Optional[UUID] = None         # controller internal id
    vm_uuid: Optional[str] = None        # xen/xoa uuid (hypervisor id)
    source_host: str
    target_host: str
    reason: Optional[str] = None
    client_request_id: Optional[str] = None


@router.post("", status_code=202)
def create_migration(payload: MigrationCreate, session: Session = Depends(db.get_db)):
    # Resolve vm_id from vm_uuid if needed
    vm_id = payload.vm_id
    if vm_id is None and payload.vm_uuid:
        vm = session.query(VM).filter(VM.xen_uuid == payload.vm_uuid).first()
        if not vm:
            raise HTTPException(status_code=400, detail="vm_uuid not found in controller")
        vm_id = vm.id

    if vm_id is None:
        # Return clear validation-style error for missing identifier
        raise HTTPException(status_code=400, detail="vm_id or vm_uuid is required")

    # idempotency via client_request_id
    if payload.client_request_id:
        existing = (
            session.query(Migration)
            .filter(Migration.client_request_id == payload.client_request_id)
            .first()
        )
        if existing:
            return {"migration_id": existing.id, "status": existing.status}

    m = Migration(
        vm_id=vm_id,
        source_host=payload.source_host,
        target_host=payload.target_host,
        reason=payload.reason,
        client_request_id=payload.client_request_id,
        status="queued",
        progress=0,
    )
    session.add(m)
    session.commit()
    session.refresh(m)

    # Lazy import the migration enqueue wrapper so module import won't fail at startup
    try:
        from app.migration.tasks import migrate_vm_task_delay
    except Exception as exc:
        # fallback: return created record but warn that worker not queued
        return {"migration_id": m.id, "status": "queued", "note": f"task import failed: {exc}"}

    # enqueue the migration (the wrapper will handle whether Celery is available)
    try:
        migrate_vm_task_delay(str(m.id))
    except Exception as exc:
        # If enqueue fails, still return queued, but include error detail
        return {"migration_id": m.id, "status": "queued", "enqueue_error": str(exc)}

    return {"migration_id": m.id, "status": "queued"}


@router.get("/{migration_id}")
def get_migration(migration_id: UUID, session: Session = Depends(db.get_db)):
    m = session.query(Migration).filter(Migration.id == migration_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="migration not found")
    return {
        "migration_id": m.id,
        "vm_id": m.vm_id,
        "source_host": m.source_host,
        "target_host": m.target_host,
        "status": m.status,
        "progress": m.progress,
        "started_at": m.started_at,
        "finished_at": m.finished_at,
        "details": m.details,
    }
