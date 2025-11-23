# app/xoa_client.py
import requests
import json
from typing import Any, Dict, Optional
from app.config import settings

# Optional: silence insecure HTTPS warnings (self-signed)
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

class XOARestClient:
    def __init__(self, verify_ssl: bool = False, timeout: int = 20):
        raw_base = getattr(settings, "xoa_base_url", None)
        if not raw_base:
            raise RuntimeError("XOA_BASE_URL not set in settings")
        raw_base = raw_base.rstrip("/")

        if "/rest/v0" in raw_base:
            self.base = raw_base.split("/rest/v0", 1)[0]
        elif raw_base.endswith("/rest"):
            self.base = raw_base.rsplit("/rest", 1)[0]
        else:
            self.base = raw_base

        self.rest_prefix = "/rest/v0"
        self.timeout = timeout
        self.verify = verify_ssl
        self.token = getattr(settings, "xoa_token", None)

        self.session = requests.Session()

        # --- Important: set cookie explicitly in session.cookies (more robust) ---
        if self.token:
            self.session.cookies.set("authenticationToken", self.token, domain=self._domain_for_cookie(), path="/")
        # Also keep header fallback
        if self.token:
            self.session.headers.update({"Cookie": f"authenticationToken={self.token}"})
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _domain_for_cookie(self) -> Optional[str]:
        # extract host portion for cookie domain if possible (used above)
        try:
            # raw base may include scheme
            host = self.base.split("://", 1)[-1].split("/", 1)[0]
            return host
        except Exception:
            return None

    def _build_path_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        if path.startswith(self.rest_prefix):
            url = f"{self.base}{path}"
        else:
            url = f"{self.base}{self.rest_prefix}{path}"
        return url

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._build_path_url(path)
        # debug prints:
        print(f"[XOARestClient] GET -> {url}")
        # print cookie we will send for debugging
        print(f"[XOARestClient] sending cookie: authenticationToken={self.session.cookies.get('authenticationToken')}")
        r = self.session.get(url, params=params, timeout=self.timeout, verify=self.verify)
        ctype = (r.headers.get("Content-Type") or "")
        if "application/json" not in ctype:
            raise RuntimeError(f"Unexpected non-JSON response from XOA REST (status={r.status_code}). Body snippet: {r.text[:400]}")
        return r.json()

    def _post(self, path: str, data: Any = None, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._build_path_url(path)
        print(f"[XOARestClient] POST -> {url}")
        print(f"[XOARestClient] sending cookie: authenticationToken={self.session.cookies.get('authenticationToken')}")
        body = json.dumps(data) if data is not None else None
        r = self.session.post(url, data=body, params=params, timeout=self.timeout, verify=self.verify)
        ctype = (r.headers.get("Content-Type") or "")
        if "application/json" not in ctype:
            raise RuntimeError(f"Unexpected non-JSON response from XOA REST (status={r.status_code}). Body snippet: {r.text[:400]}")
        return r.json()

    # helpers
    def list_pools(self) -> list:
        return self._get("/pools")

    def list_templates_in_pool(self, pool_uuid: str) -> list:
        return self._get(f"/pools/{pool_uuid}/vms", params={"type":"template"})

    def get_vm(self, vm_uuid_or_path: str) -> dict:
        if vm_uuid_or_path.startswith("/rest/"):
            path = vm_uuid_or_path
        else:
            path = f"/vms/{vm_uuid_or_path}"
        return self._get(path)

    def create_vm_on_pool(self, pool_uuid: str, payload: dict, sync: bool = False) -> dict:
        path = f"/pools/{pool_uuid}/actions/create_vm"
        params = {"sync":"true"} if sync else None
        return self._post(path, data=payload, params=params)

def get_xoa_rest_client() -> XOARestClient:
    return XOARestClient()
