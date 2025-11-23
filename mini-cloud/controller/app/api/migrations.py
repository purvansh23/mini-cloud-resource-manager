# controller/app/api/migrations.py  (example path)
from fastapi import APIRouter, Query
from typing import List, Optional
from app import db
from app.models import Migration  # adapt import path if different
from sqlalchemy import select
from pydantic import BaseModel

router = APIRouter(prefix="/migrations", tags=["migrations"])

class MigrationOut(BaseModel):
    id: str
    vm_id: str
    source_host: Optional[str] = None
    target_host: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None

@router.get("/", response_model=List[MigrationOut])
def list_migrations(status: Optional[str] = Query(None, description="Comma-separated statuses, e.g. PENDING,RUNNING")):
    """
    List migrations. Optional ?status=CSV to filter by status values.
    """
    session = db.SessionLocal()
    try:
        q = select(Migration)
        if status:
            wanted = [s.strip().upper() for s in status.split(",") if s.strip()]
            q = q.where(Migration.status.in_(wanted))
        rows = session.execute(q).scalars().all()
        out = []
        for m in rows:
            out.append({
                "id": m.id,
                "vm_id": m.vm_id,
                "source_host": getattr(m, "source_host", None),
                "target_host": getattr(m, "target_host", None),
                "status": getattr(m, "status", None),
                "created_at": getattr(m, "created_at", None).isoformat() if getattr(m, "created_at", None) else None
            })
        return out
    finally:
        session.close()
