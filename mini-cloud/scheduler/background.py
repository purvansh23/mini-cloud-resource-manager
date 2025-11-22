# scheduler/background.py
import asyncio
import time
import logging
from typing import Dict, List
from .api_client import ControllerClient
from .planner import Planner
from .models import Host, VM, Alert
from .policies import is_host_overloaded
from .config import REBALANCE_INTERVAL, MAX_CONCURRENT_MIGRATIONS

logger = logging.getLogger("scheduler.background")

class SchedulerService:
    def __init__(self, client: ControllerClient):
        self.client = client
        self.planner = Planner()
        self.running_migrations = 0
        self.lock = asyncio.Lock()

    async def start_periodic(self):
        while True:
            try:
                await self.run_periodic_cycle()
            except Exception as e:
                logger.exception("Periodic cycle failed: %s", e)
            await asyncio.sleep(REBALANCE_INTERVAL)

    async def run_periodic_cycle(self):
        logger.info("Starting periodic rebalance cycle")
        hosts_json = self.client.get_hosts()
        vms_json = self.client.get_vms()

        hosts = [Host(**h) for h in hosts_json]
        vms = [VM(**v) for v in vms_json]

        vms_by_host = {}
        for vm in vms:
            vms_by_host.setdefault(vm.host_id, []).append(vm)

        plan = self.planner.plan_rebalance(hosts, vms_by_host)
        logger.info("Periodic plan proposals: %d", len(plan))
        await self.submit_plan(plan)

    async def submit_plan(self, plan):
        # Refresh running migrations count from controller to respect cluster-wide limits
        try:
            current_running = self.client.get_running_migrations_count()
            # initialize or sync our in-memory counter
            self.running_migrations = int(current_running or 0)
        except Exception:
            logger.warning("Could not fetch running migrations count from controller; using local counter")

        async with self.lock:
            for vm, dst in plan:
                if self.running_migrations >= MAX_CONCURRENT_MIGRATIONS:
                    logger.info("Reached max concurrent migrations (local=%d, max=%d) - pausing plan submission",
                                self.running_migrations, MAX_CONCURRENT_MIGRATIONS)
                    break
                try:
                    logger.info("Requesting migration for vm %s -> %s", vm.vm_uuid, dst)
                    # call controller API (note: ControllerClient.request_migration expects vm_uuid, source_host, target_host)
                    res = self.client.request_migration(vm.vm_uuid, vm.host_id, dst, priority="normal", reason="periodic_rebalance")
                    logger.info("Controller accepted migration response: %s", res)
                    # If controller returned a created migration (expected), increment counter
                    # We are defensive: if res contains migration id -> increment; otherwise still increment conservatively.
                    mig_id = None
                    if isinstance(res, dict):
                        mig_id = res.get("id") or res.get("migration_id") or res.get("migration", {}).get("id")
                    self.running_migrations += 1
                    logger.info("Scheduled migration (controller id=%s). Running migrations now: %d",
                                mig_id, self.running_migrations)
                except Exception as e:
                    logger.exception("Failed to request migration: %s", e)

    async def handle_alert(self, alert: Alert):
        logger.info("Received alert for host %s level=%s", alert.host_id, alert.level)
        # fetch fresh snapshot
        hosts_json = self.client.get_hosts()
        vms_json = self.client.get_vms()
        hosts = [Host(**h) for h in hosts_json]
        vms = [VM(**v) for v in vms_json]
        alert_host = next((h for h in hosts if h.host_id == alert.host_id), None)
        if not alert_host:
            logger.warning("Alert host %s not found in host list", alert.host_id)
            return {"status":"host_not_found"}

        # if the host is already overloaded, plan emergency
        plan = self.planner.plan_emergency(alert_host, hosts, [vm for vm in vms if vm.host_id == alert_host.host_id])
        if not plan:
            # no migration possible — throttle host at controller
            logger.info("No emergency migration possible for host %s, throttling", alert.host_id)
            try:
                self.client.throttle_host(alert.host_id, duration_seconds=300, reason=f"alert_{alert.level}")
            except Exception as e:
                logger.exception("Failed to throttle host: %s", e)
            return {"status":"throttled"}
        # submit emergency plan immediately
        await self.submit_plan(plan)
        return {"status":"migration_requested", "plan": [(p[0].vm_uuid, p[1]) for p in plan]}
