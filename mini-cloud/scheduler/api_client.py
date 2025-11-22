# scheduler/api_client.py
import requests
from typing import List, Dict, Any, Optional
from .config import CONTROLLER_BASE_URL, CONTROLLER_TOKEN
import os
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ControllerClient:
    def __init__(self, base_url=None, token=None, timeout=5):
        self.base_url = base_url or os.getenv("CONTROLLER_BASE_URL", "http://localhost:8001")
        self.token = token or os.getenv("CONTROLLER_TOKEN")
        self.timeout = timeout
        self.session = self._make_session(self.token)

    def _make_session(self, token):
        s = Session()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        s.headers.update(headers)
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(502,503,504))
        s.mount("http://", HTTPAdapter(max_retries=retries))
        s.mount("https://", HTTPAdapter(max_retries=retries))
        return s

    def get_hosts(self):
        url = f"{self.base_url.rstrip('/')}/hosts"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_vms(self):
        """
        Robust getter for /vms endpoint.
        Tries both /vms and /vms/ variants and falls back to [] on 404 or errors.
        """
        candidates = [
            f"{self.base_url.rstrip('/')}/vms/",
            f"{self.base_url.rstrip('/')}/vms"
        ]
        for url in candidates:
            try:
                resp = self.session.get(url, timeout=self.timeout)
                # skip 404/405 and try next
                if resp.status_code in (404, 405):
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception:
                # try next candidate
                continue
        # nothing succeeded — return empty list (scheduler will log but won't crash)
        return []

    def request_migration(self, vm_uuid: str, source_host: str, target_host: str, priority: str = "normal",
                          reason: Optional[str] = None, client_request_id: Optional[str] = None):
        """
        Request the controller to create a migration row and enqueue the worker.
        Returns controller JSON response (should contain migration id and status).
        Payload shape expected by controller:
        {
            "vm_id": "<vm_uuid>",
            "source_host": "<host_uuid>",
            "target_host": "<host_uuid>",
            "priority": "normal",
            "reason": "...",
            "client_request_id": "...optional client id..."
        }
        """
        url = f"{self.base_url.rstrip('/')}/migration/request"
        payload = {
            "vm_id": vm_uuid,
            "source_host": source_host,
            "target_host": target_host,
            "priority": priority,
            "reason": reason,
        }
        if client_request_id:
            payload["client_request_id"] = client_request_id

        resp = self.session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def throttle_host(self, host_id: str, duration_seconds: int, reason: Optional[str] = None) -> Dict[str, Any]:
        payload = {"duration_seconds": duration_seconds, "reason": reason}
        resp = self.session.post(f"{self.base_url}/hosts/{host_id}/throttle", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_running_migrations_count(self) -> int:
        """
        Try several controller endpoints to count pending/running migrations.

        IMPORTANT:
        Your Controller exposes GET on `/migrations/` (with trailing slash),
        not on `/migrations`. Scheduler must therefore try the trailing slash
        version first, or it will receive 405 Method Not Allowed.

        Returns:
            int: number of PENDING or RUNNING migrations.
        """
        endpoints_to_try = [
            f"{self.base_url.rstrip('/')}/migrations/?status=PENDING,RUNNING",
            f"{self.base_url.rstrip('/')}/migrations/?status=PENDING,RUNNING".rstrip("?"),
            f"{self.base_url.rstrip('/')}/migrations/",
            f"{self.base_url.rstrip('/')}/migrations",
            f"{self.base_url.rstrip('/')}/jobs?status=PENDING,RUNNING",
            f"{self.base_url.rstrip('/')}/jobs",
        ]

        for url in endpoints_to_try:
            try:
                resp = self.session.get(url, timeout=self.timeout)

                # Skip endpoints that do not support GET
                if resp.status_code in (404, 405):
                    continue

                resp.raise_for_status()
                data = resp.json()

                # If the response is already filtered by ?status=...
                if isinstance(data, list):
                    return len(data)

                # If dictionary with status field per migration
                if isinstance(data, dict) and "items" in data:
                    items = data.get("items", [])
                    count = 0
                    for item in items:
                        st = item.get("status")
                        if st and str(st).upper() in ("PENDING", "RUNNING"):
                            count += 1
                    return count

            except Exception:
                # This endpoint failed, try next
                continue

        # No endpoint succeeded
        return 0
