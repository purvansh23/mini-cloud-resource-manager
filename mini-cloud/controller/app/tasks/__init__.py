# app/tasks/__init__.py
# Export commonly used names for convenience
from .celery_app import celery  # the Celery instance
from .jobs import create_vm_job  # the main task function
__all__ = ["celery", "create_vm_job"]
