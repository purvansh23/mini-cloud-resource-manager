# app/migration/tasks.py
import importlib
import traceback
from typing import Optional, Any, Dict
import logging
from celery import Celery
from app import db
from app.models import Migration
from app.migration.orchestrator import MigrationOrchestrator
from app.migration.lock import RedisLock

log = logging.getLogger(__name__)

# --- helper to locate your celery app instance dynamically ---
def _find_celery_app() -> Optional[Celery]:
    candidates = [
        ("app.tasks.celery_app", "celery_app"),
        ("app.tasks.celery_app", "celery"),
        ("app.tasks", "celery_app"),
        ("app.tasks", "celery"),
        ("app.tasks.celery_app", "app"),
    ]
    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, attr):
                obj = getattr(mod, attr)
                if isinstance(obj, Celery):
                    return obj
        except Exception:
            continue
    return None

CELERY_APP = _find_celery_app()
if CELERY_APP is None:
    log.warning("WARNING: Celery app not found by app.migration.tasks; tasks will fallback to synchronous execution until worker is configured.")


# --- synchronous runner used both by Celery task and by fallback ---
def _run_migration_sync(migration_id: str) -> Dict[str, Any]:
    """
    Run the migration synchronously (used by the Celery task or fallback).
    Returns dict with status or error.
    """
    session = db.SessionLocal()
    try:
        # fetch migration row
        migration = session.query(Migration).filter(Migration.id == migration_id).first()
        if not migration:
            log.error("Migration id %s not found", migration_id)
            return {"error": "not_found"}

        # acquire per-VM lock
        lock_key = f"migration:vm:{migration.vm_id}"
        try:
            with RedisLock(lock_key, ttl=300, wait=10, sleep=0.1):
                # re-fetch with lock and for update
                migration = session.query(Migration).filter(Migration.id == migration_id).with_for_update().first()
                if not migration:
                    log.error("Migration disappeared after lock acquisition: %s", migration_id)
                    return {"error": "not_found_after_lock"}

                # if already in-progress or completed, no-op
                if migration.status in ("running", "completed"):
                    log.info("Migration %s already in status %s, skipping", migration_id, migration.status)
                    return {"status": migration.status}

                # mark running
                migration.status = "running"
                migration.started_at = func_now()
                migration.progress = 1
                session.add(migration)
                session.commit()

                # ********** Pre-check: allow either guest flag OR auto-detect PV capability **********
                # Instantiate orchestrator early so we can use its detection helper.
                try:
                    orch = MigrationOrchestrator(session, migration, simulate=False)
                except Exception as e:
                    tb = traceback.format_exc()
                    log.exception("Failed to create MigrationOrchestrator for migration %s: %s", migration_id, e)
                    migration.status = "failed"
                    migration.details = {"error": "orchestrator_init_failed", "traceback": tb}
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    return {"status": "failed", "error": "orchestrator_init_failed"}

                try:
                    can_migrate, reason = orch.is_live_migratable(str(migration.vm_id))
                except Exception as e:
                    tb = traceback.format_exc()
                    log.exception("is_live_migratable check failed for migration %s: %s", migration_id, e)
                    migration.status = "failed"
                    migration.details = {"error": "migrate_check_failed", "traceback": tb}
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    return {"status": "failed", "error": "migrate_check_failed"}

                if not can_migrate:
                    msg = f"VM not eligible for live migration: {reason}"
                    log.warning("Migration %s rejected: %s", migration_id, msg)
                    migration.status = "failed"
                    migration.details = {"error": msg}
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    return {"status": "failed", "error": msg}

                # --- Run orchestrator (the actual migration logic) ---
                try:
                    result = orch.run()
                except Exception as e:
                    # make sure we capture exceptions from orchestration
                    tb = traceback.format_exc()
                    log.exception("Orchestrator exception for migration %s: %s", migration_id, e)
                    migration.status = "failed"
                    migration.details = {"error": str(e), "traceback": tb}
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    return {"ok": False, "error": str(e)}

                # finalize according to result
                if result.get("ok"):
                    migration.status = "completed"
                    migration.progress = 100
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    log.info("Migration %s completed", migration_id)
                    return {"status": "completed"}
                else:
                    migration.status = "failed"
                    migration.details = {"error": result.get("error")}
                    migration.finished_at = func_now()
                    session.add(migration)
                    session.commit()
                    log.error("Migration %s failed: %s", migration_id, result.get("error"))
                    return {"status": "failed", "error": result.get("error")}
        except TimeoutError as e:
            log.warning("Could not acquire lock for migration %s: %s", migration_id, e)
            return {"error": "lock_acquire_failed", "detail": str(e)}
    finally:
        session.close()


# --- If a Celery app exists, register a Celery task to run the sync runner ---
if CELERY_APP is not None:
    @CELERY_APP.task(name="app.migration.tasks.migrate_vm_task", bind=True, max_retries=3, default_retry_delay=10)
    def migrate_vm_task(self, migration_id: str):
        log.info("Celery task migrate_vm_task invoked for %s", migration_id)
        try:
            return _run_migration_sync(migration_id)
        except Exception as exc:
            log.exception("Unexpected error in migrate_vm_task for %s: %s", migration_id, exc)
            # record failure into DB as last-resort
            try:
                session = db.SessionLocal()
                mg = session.query(Migration).filter(Migration.id == migration_id).first()
                if mg:
                    mg.status = "failed"
                    mg.details = {"error": str(exc)}
                    mg.finished_at = func_now()
                    session.add(mg)
                    session.commit()
            except Exception:
                log.exception("Failed to mark migration as failed in DB for %s", migration_id)
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            # attempt celery retry
            try:
                self.retry(exc=exc)
            except Exception:
                raise


# --- public wrapper used by API router ---
def migrate_vm_task_delay(migration_id: str):
    """
    Enqueue a migration task. If Celery is available we send_task or call registered task; else run synchronously.
    """
    if CELERY_APP:
        try:
            # prefer send_task (works even if task object not present)
            CELERY_APP.send_task("app.migration.tasks.migrate_vm_task", args=[migration_id])
            return True
        except Exception as e:
            log.warning("CELERY send_task failed, trying fallback apply_async: %s", e)
            task_obj = CELERY_APP.tasks.get("app.migration.tasks.migrate_vm_task")
            if task_obj:
                task_obj.apply_async(args=[migration_id])
                return True
            # last-resort sync
            return _run_migration_sync(migration_id)
    else:
        # no celery — run synchronously (dev fallback)
        return _run_migration_sync(migration_id)


# small helper
def func_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
