# app/migration/clients/host_agent_client.py
import httpx
from typing import Tuple

DEFAULT_TIMEOUT = 5.0

class HostAgentClient:
    def __init__(self, timeout: float = DEFAULT_TIMEOUT, verify: bool = True, token: str | None = None):
        self.timeout = timeout
        self.verify = verify
        self.token = token

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _base_url(self, host: str):
        # adapt scheme/port to your host-agent
        return f"http://{host}:8001"

    def check_host_ready(self, host: str) -> Tuple[bool, str]:
        url = f"{self._base_url(host)}/health"
        try:
            r = httpx.get(url, timeout=self.timeout, verify=self.verify, headers=self._headers())
            if r.status_code == 200:
                return True, r.text
            return False, f"{r.status_code}: {r.text}"
        except Exception as e:
            return False, str(e)

    def prepare_source(self, host: str, vm_id: str) -> Tuple[bool, str]:
        url = f"{self._base_url(host)}/migration/prepare_source"
        try:
            r = httpx.post(url, json={"vm_id": str(vm_id)}, timeout=self.timeout, verify=self.verify, headers=self._headers())
            if r.status_code == 200:
                return True, r.text
            return False, f"{r.status_code}: {r.text}"
        except Exception as e:
            return False, str(e)

    def prepare_target(self, host: str, vm_id: str) -> Tuple[bool, str]:
        url = f"{self._base_url(host)}/migration/prepare_target"
        try:
            r = httpx.post(url, json={"vm_id": str(vm_id)}, timeout=self.timeout, verify=self.verify, headers=self._headers())
            if r.status_code == 200:
                return True, r.text
            return False, f"{r.status_code}: {r.text}"
        except Exception as e:
            return False, str(e)
