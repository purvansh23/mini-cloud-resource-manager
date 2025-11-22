# scheduler/main.py
import logging
import uvicorn
from fastapi import FastAPI, BackgroundTasks
from .api_client import ControllerClient
from .background import SchedulerService
from .models import Alert
from .config import LOG_LEVEL

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("scheduler")

app = FastAPI(title="Mini-Cloud Scheduler")

client = ControllerClient()
service = SchedulerService(client)

@app.on_event("startup")
async def startup_event():
    # start periodic runner in background
    import asyncio
    asyncio.create_task(service.start_periodic())
    logger.info("Scheduler service started and periodic task scheduled")

@app.post("/scheduler/alert")
async def receive_alert(alert: Alert, background: BackgroundTasks):
    # process alert in background to reply quickly
    background.add_task(service.handle_alert, alert)
    return {"status":"accepted"}

@app.get("/scheduler/health")
async def health():
    return {"status":"ok"}

if __name__ == "__main__":
    uvicorn.run("scheduler.main:app", host="0.0.0.0", port=9000, log_level="info")
