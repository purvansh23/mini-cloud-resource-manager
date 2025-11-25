from fastapi import FastAPI
from app.api import hosts, metrics, vms, jobs, xoa
from app.migration.api import router as migration_router
from app.api.hosts import router as hosts_router
from app.api import migrations
from app.api import apiVm, apiMigration, apiMetrics

app = FastAPI(title="Mini Cloud Controller API")

app.include_router(hosts_router)
app.include_router(metrics.router)
app.include_router(vms.router)
app.include_router(jobs.router)
app.include_router(xoa.router)
app.include_router(migration_router)
app.include_router(migrations.router)
app.include_router(apiVm.router)
app.include_router(apiMigration.router)
app.include_router(apiMetrics.router)


@app.get("/")
def root():
    return {"status": "controller up"}
