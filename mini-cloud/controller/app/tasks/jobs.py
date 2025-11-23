# app/tasks/jobs.py
import traceback
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app import crud
from app.xoa_client import get_xoa_rest_client

# import celery instance
from app.tasks.celery_app import celery

# Optional SSH driver helpers (if you still want SSH fallback)
try:
    from app.xen_ssh_driver import get_vm_uuid_by_name, clone_vm_from_template, start_vm
    _HAS_SSH_DRIVER = True
except Exception:
    _HAS_SSH_DRIVER = False

# DB session factory for tasks (separate engine to avoid forking issues)
DATABASE_URL = (
    f"postgresql://{settings.db_user}:{settings.db_pass}"
    f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
)
task_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
TaskSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=task_engine)

def task_get_db():
    db = TaskSessionLocal()
    try:
        yield db
    finally:
        db.close()

@celery.task(bind=True, acks_late=True)
def create_vm_job(self, job_id: str, payload: dict):
    """
    Create VM job. Two modes:
      - XOA mode: payload['use_xoa'] = True, must include pool_uuid and (template_uuid or other create params)
      - SSH mode (fallback): payload must include 'host' and 'dom0_password' and template_name
    Updates job status via crud.update_job_status.
    """
    db_gen = task_get_db()
    db = next(db_gen)
    try:
        crud.update_job_status(db, job_id, "running")

        # --------------- XOA REST path ---------------
        if payload.get("use_xoa"):
            client = get_xoa_rest_client()
            pool_uuid = payload.get("pool_uuid")
            if not pool_uuid:
                raise ValueError("pool_uuid required for XOA path")

            # Build create payload according to XOA rest v0 shape (use what you need)
            body = {
                "name_label": payload.get("name") or payload.get("name_label") or f"vm-{job_id}",
                "template": payload.get("template_uuid"),
                # optional: you can include disks, memory, cpu fields if required
            }
            # allow custom extra body fields from payload['xoa_body'] if present
            extra = payload.get("xoa_body")
            if isinstance(extra, dict):
                body.update(extra)

            try:
                res = client.create_vm_on_pool(pool_uuid, body, sync=payload.get("sync", False))
                crud.update_job_status(db, job_id, "success", {"xoa_result": res})
                return {"xoa_result": res}
            except Exception as e:
                tb = traceback.format_exc()
                crud.update_job_status(db, job_id, "failed", {"error": str(e), "traceback": tb})
                raise

        # --------------- SSH/XE fallback path ---------------
        # require ssh driver to be available
        if not _HAS_SSH_DRIVER:
            raise RuntimeError("SSH/XE driver not available and payload not using XOA")

        host = payload.get("host")
        dom0_user = payload.get("dom0_user", "root")
        dom0_pw = payload.get("dom0_password")
        template_name = payload.get("template_name")
        new_name = payload.get("name") or f"vm-{job_id}"

        if not host or not dom0_pw or not template_name:
            raise ValueError("host, dom0_password and template_name are required for SSH-based creation")

        # Step 1: find template uuid on host
        try:
            template_uuid = get_vm_uuid_by_name(host, dom0_user, dom0_pw, template_name)
            if not template_uuid:
                raise RuntimeError(f"Template '{template_name}' not found on host {host}")
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"Failed to fetch template uuid: {e}\n{tb}")

        # Step 2: clone template
        try:
            new_uuid = clone_vm_from_template(host, dom0_user, dom0_pw, template_uuid, new_name)
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"Failed to clone VM from template: {e}\n{tb}")

        # Step 3: start the VM
        try:
            start_vm(host, dom0_user, dom0_pw, new_uuid)
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"VM cloned (uuid={new_uuid}) but failed to start: {e}\n{tb}")

        result = {"vm_uuid": new_uuid, "host": host, "name": new_name}
        crud.update_job_status(db, job_id, "success", result)
        return result

    except Exception as e:
        tb = traceback.format_exc()
        try:
            crud.update_job_status(db, job_id, "failed", {"error": str(e), "traceback": tb})
        except Exception:
            pass
        # Re-raise to mark Celery task as failed
        raise
    finally:
        try:
            next(db_gen, None)
        except Exception:
            pass
