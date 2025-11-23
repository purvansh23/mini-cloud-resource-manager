# app/api/vms_iso.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import uuid
import json
from sqlalchemy import text
from app.config import settings
from app.tasks.jobs import create_vm_job
from app.db import get_db  # if you have a dependency to get DB session; else we'll use engine directly
from sqlalchemy import create_engine

router = APIRouter()

# If your app already mounts a router, import and include this router in app.main:
# from app.api.vms_iso import router as vms_iso_router
# app.include_router(vms_iso_router)

class VMCreateFromISO(BaseModel):
    name: str = Field(..., description="Name label for the new VM")
    host: str = Field(..., description="XCP-ng host IP to create the VM on (Dom0)")
    dom0_user: str = Field("root", description="Dom0 SSH user (default root)")
    dom0_password: str = Field(..., description="Dom0 SSH password (or use key-based auth later)")
    iso_name: str = Field(..., description="ISO filename in the ISO SR")
    sr_name: str | None = Field(None, description="SR name to create VM disk in (eg 'NFS SR')")
    network_name: str | None = Field(None, description="Network name to attach (eg 'Pool-wide network associated with eth0')")
    ram_mb: int = Field(2048, description="RAM in MiB")
    vcpus: int = Field(2, description="vCPUs")

# Create DB engine for direct SQL insert (separate from task engine)
SQLALCHEMY_DATABASE_URL = (
    f"postgresql://{settings.db_user}:{settings.db_pass}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
)
_engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

@router.post("/vms/create_from_iso")
def create_vm_from_iso_endpoint(payload: VMCreateFromISO):
    """
    Create a job to create a VM from ISO. The endpoint will:
    1) Insert a job record into the jobs table with status 'queued'
    2) Enqueue the create_vm_job Celery task with job_id and payload dict
    3) Return the job_id to the caller
    """
    job_id = str(uuid.uuid4())
    payload_dict = payload.dict()

    # Insert job row into jobs table reliably using SQL (adapt if your jobs schema differs)
    # This uses a minimal schema assumption: table 'jobs' has columns id (text/uuid), status (text), payload (jsonb), created_at (timestamp default).
    # If your schema differs, adjust the SQL accordingly.
    insert_sql = text(
        "INSERT INTO jobs (id, status, payload, created_at) VALUES (:id, :status, :payload::jsonb, now())"
    )
    try:
        with _engine.begin() as conn:
            conn.execute(insert_sql, {"id": job_id, "status": "queued", "payload": json.dumps(payload_dict)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job row: {e}")

    # Enqueue Celery task (async)
    try:
        create_vm_job.delay(job_id, payload_dict)
    except Exception as e:
        # If enqueue fails, mark job failed in DB and report
        update_sql = text("UPDATE jobs SET status=:status WHERE id=:id")
        with _engine.begin() as conn:
            conn.execute(update_sql, {"status": "failed", "id": job_id})
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {e}")

    return {"job_id": job_id, "status": "queued"}
