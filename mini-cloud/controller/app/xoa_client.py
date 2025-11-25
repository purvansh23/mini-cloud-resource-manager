import requests
import os

XOA_URL = os.environ.get("XOA_URL", "http://10.20.24.77")
XOA_TOKEN = os.environ.get("XOA_TOKEN", "")

def _headers():
    return {"Authorization": f"Bearer {XOA_TOKEN}"} if XOA_TOKEN else {}

def fetch_live_metrics(host_ip):
    """
    Example: call to XOA or to a simple per-host metric endpoint.
    This function should be adapted to your actual XOA endpoints.
    """
    try:
        # If you have XOA metrics endpoint, replace with real path
        url = f"{XOA_URL}/api/hosts/{host_ip}/metrics"
        resp = requests.get(url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    # fallback dummy metrics for robust execution
    return {"cpu": 0.0, "memory": 0.0, "vms": 0}
