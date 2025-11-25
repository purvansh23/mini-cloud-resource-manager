from app.db import SessionLocal
from app.metrics_utils import calculate_host_score
from app.xoa_client import fetch_live_metrics
from app import models
import time


def collect_metrics():
    db = SessionLocal()
    try:
        hosts = db.query(models.Host).all()
        for host in hosts:
            # fetch_live_metrics should reach XOA or other metric source
            data = fetch_live_metrics(host.ip)
            metric = models.HostMetric(
                host_id=host.id,
                cpu_percent=data.get("cpu", 0.0),
                mem_percent=data.get("memory", 0.0),
                vms_running=data.get("vms", 0),
                ts=int(time.time())
            )
            db.add(metric)
            db.commit()
    finally:
        db.close()
