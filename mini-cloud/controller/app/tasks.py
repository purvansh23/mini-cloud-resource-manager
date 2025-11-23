# app/tasks.py
import time
from celery import Celery
from app.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import crud

celery_app = Celery("controller_tasks", broker=settings.redis_url, backend=settings.redis_url)

DATABASE_URL = f"postgresql://{settings.db_user}:{settings.db_pass}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
task_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
TaskSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=task_engine)

def task_get_db():
    db = TaskSessionLocal()
    try:
        yield db
    finally:
        db.close()

@celery_app.task(bind=True, acks_late=True)
def create_vm_job(self, data):
    job_id = data.get("job_id")
    payload = data.get("payload", {})
    db = next(task_get_db())
    crud.update_job_status(db, job_id, "running")
    try:
        # Simulate creation
        time.sleep(2)
        result = {"message": "vm_created_stub", "vm_name": payload.get("name")}
        crud.update_job_status(db, job_id, "success", result=result)
        return result
    except Exception as exc:
        crud.update_job_status(db, job_id, "failed", result={"error": str(exc)})
        raise self.retry(exc=exc, countdown=5, max_retries=3)
