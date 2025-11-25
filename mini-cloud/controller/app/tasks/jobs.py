# app/tasks/jobs.py
import traceback
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app import crud
from app.xoa_client import get_xoa_rest_client
from app.scheduler import auto_migrate, migrate_vm

# import celery instance (your project uses `celery`, not `celery_app`)
from app.tasks.celery_app import celery

# Optional SSH driver helpers (if you still want SSH fallback)
try:
    from app.xen_ssh_driver import get_vm_uuid_by_name, clone_vm_from_template, start_vm
    _HAS_SSH_DRIVER = True
except Exception:
    _HAS_SSH_DRIVER = False

# Try both snake_case and CamelCase module names for the collector helper
try:
    from app.tasks.collect_metrics import collect_metrics
except Exception:  # pragma: no cover
    try:
        from app.tasks.collectMetrics import collect_metrics  # fallback to CamelCase file
    except Exception:
        collect_metrics = None  # will be checked at runtime

logger = logging.getLogger(__name__)

# ----------------------------
# DB session factory for tasks
# (separate engine to avoid forking issues)
# ----------------------------
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

# ============================
# VM CREATION (XOA/SSH)
# ============================
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

            # Build create payload according to XOA REST shape (extend via xoa_body)
            body = {
                "name_label": payload.get("name") or payload.get("name_label") or f"vm-{job_id}",
                "template": payload.get("template_uuid"),
            }
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

# ============================
# PERIODIC / MAINTENANCE TASKS
# ============================

@celery.task(name="app.tasks.jobs.collect_metrics_job")
def collect_metrics_job():
    if collect_metrics is None:
        # keep the task from failing the whole beat loop if the module isn't present
        logger.error("collect_metrics module not found; skipping metrics collection")
        return {"status": "error", "error": "collect_metrics not available"}
    try:
        collect_metrics()
        return {"status": "success"}
    except Exception as e:
        logger.exception("collect_metrics_job failed")
        return {"status": "error", "error": str(e)}

@celery.task(name="app.tasks.jobs.migrate_hosts_job")
def migrate_hosts_job():
    try:
        print("[MIGRATION] Checking if migration is needed")
        result = auto_migrate()
        print("[MIGRATION] Result:", result)
        return result
    except Exception as e:
        print("[MIGRATION] ERROR:", e)
        return {"error": str(e)}

# Celery Beat schedule (kept identical to the report, using your `celery` instance)
celery.conf.beat_schedule = {
    "collect-host-metrics-every-2-minutes": {
        "task": "app.tasks.jobs.collect_metrics_job",
        "schedule": 120,
    },
    "migration-check-every-2-minutes": {
        "task": "app.tasks.jobs.migration_job",
        "schedule": 120,
    },
}

@celery.task(name="app.tasks.jobs.migration_job")
def migration_job():
    # Lazy import of session factory to avoid circular deps in some setups
    from app.db import SessionLocal  # type: ignore
    print("\n==================== AUTO MIGRATION CHECK =====================")
    db = SessionLocal()
    try:
        result = migrate_vm(db)
        if result:
            print(f"[AUTO-MIGRATE] Migration executed {result}")
        else:
            print("[AUTO-MIGRATE] No migration required at this cycle")
        return {"status": "checked", "result": result}
    except Exception as e:
        print(f"[AUTO-MIGRATE] ERROR {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
