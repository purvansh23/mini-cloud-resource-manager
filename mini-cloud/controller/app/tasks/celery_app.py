# controller/app/tasks/celery_app.py
from celery import Celery
from app.config import settings
import os

# support env overrides but fall back to settings
REDIS_BROKER = os.getenv("CELERY_BROKER_URL", None) or getattr(settings, "redis_url", "redis://localhost:6379/0")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", None) or getattr(settings, "redis_url", "redis://localhost:6379/1")

# ensure modules that define tasks are imported by workers at startup
# add any other modules that contain @celery.task definitions here
INCLUDE_MODULES = [
    "app.tasks.jobs",
    "app.migration.tasks",
]

# create instance with the name the rest of the code expects
celery_app = Celery(
    "controller_tasks",
    broker=REDIS_BROKER,
    backend=CELERY_BACKEND,
    include=INCLUDE_MODULES,
)

# keep an alias named `celery` too (useful for CLI where people expect -A x.celery)
celery = celery_app

# sane defaults
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=1800,  # seconds, adjust as needed
)
