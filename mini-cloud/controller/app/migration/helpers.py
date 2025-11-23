# app/migration/helpers.py
import uuid
from app import db
from app.models import Migration
from app.migration.tasks import migrate_vm_task_delay, func_now
from sqlalchemy.exc import IntegrityError
import logging

log = logging.getLogger("migration.helpers")

def create_and_enqueue_migration(vm_uuid: str, source_host_uuid: str, target_host_uuid: str, reason: str = "scheduler", metadata: dict = None):
    """
    Idempotent creation + enqueue:
      - If a pending/running migration already exists for same vm_uuid -> return existing record, created=False
      - Otherwise create migration DB row and enqueue Celery task
    Returns (migration_obj, created_now: bool)
    """
    session = db.SessionLocal()
    try:
        # 1) check for an existing pending/running migration for this VM
        existing = session.query(Migration).filter(
            Migration.vm_id == vm_uuid,
            Migration.status.in_(["pending", "running"])
        ).order_by(Migration.created_at.desc()).first()
        if existing:
            log.info("Existing migration found for vm %s -> %s, skipping new create", vm_uuid, existing.id)
            return existing, False

        # 2) create new migration record
        new_mig = Migration(
            id=str(uuid.uuid4()),
            vm_id=vm_uuid,
            source_host=source_host_uuid,
            target_host=target_host_uuid,
            status="pending",
            progress=0,
            reason=reason,
            details=metadata or {},
            created_at=func_now()
        )
        session.add(new_mig)
        session.commit()

        # 3) enqueue the celery task (non-blocking)
        try:
            migrate_vm_task_delay(new_mig.id)
            log.info("Enqueued migration task for %s -> %s (migration id=%s)", vm_uuid, target_host_uuid, new_mig.id)
        except Exception as e:
            new_mig.status = "failed"
            new_mig.details = {"error": f"enqueue_failed: {e}"}
            new_mig.finished_at = func_now()
            session.add(new_mig)
            session.commit()
            log.exception("Failed to enqueue celery task for migration %s", new_mig.id)
            return new_mig, True

        return new_mig, True
    except IntegrityError:
        session.rollback()
        existing = session.query(Migration).filter(Migration.vm_id == vm_uuid).order_by(Migration.created_at.desc()).first()
        return existing, False
    finally:
        session.close()
