#!/usr/bin/env python3
# controller/tools/sync_vms_from_xen.py
import subprocess
import requests
import json
import os
import sys

# CONFIG - edit if needed
XE_HOST = os.getenv("XEN_POOL_MASTER", "10.20.24.40")      # pool master IP with xe available
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://localhost:8001")
API_TOKEN = os.getenv("CONTROLLER_TOKEN", None)           # optional if controller requires bearer token
SSH_USER = os.getenv("SSH_USER", "root")
SSH_CMD_PREFIX = ["ssh", f"{SSH_USER}@{XE_HOST}"]

HEADERS = {"Content-Type": "application/json"}
if API_TOKEN:
    HEADERS["Authorization"] = f"Bearer {API_TOKEN}"

def run_xe(cmd_args):
    cmd = SSH_CMD_PREFIX + ["--"] + cmd_args
    # run the command and return stdout
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        return out
    except subprocess.CalledProcessError as e:
        print("Error running xe command:", e, e.output)
        raise

def _normalize_key(raw_key: str) -> str:
    """
    Normalize keys like:
      "uuid ( RO)" -> "uuid"
      "name-label ( RW)" -> "name_label"
      "power-state ( RO)" -> "power_state"
    """
    k = raw_key.strip()
    # drop any parenthetical flags like " ( RO)" or " (MRW)"
    if "(" in k:
        k = k.split("(")[0].strip()
    # normalize separators to underscore and lowercase
    k = k.replace("-", "_").replace(" ", "_").lower()
    return k

def parse_xe_vm_list(raw):
    """
    Parse output of:
      xe vm-list params=uuid,name-label,resident-on,power-state
    into list of dicts with normalized keys.
    """
    items = []
    current = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            if current:
                items.append(current)
                current = {}
            continue
        # xe lines contain "key : value"
        if ":" not in line:
            continue
        left, right = line.split(":", 1)
        key = _normalize_key(left)
        value = right.strip()
        current[key] = value if value != "" else None
    if current:
        items.append(current)
    return items

def main():
    print("Running sync from XCP-ng pool master:", XE_HOST)
    # call xe to list VMs with fields we want
    xe_fields = ["uuid","name-label","resident-on","power-state"]
    args = ["xe", "vm-list", "params=" + ",".join(xe_fields)]
    raw = run_xe(args)
    vms = parse_xe_vm_list(raw)
    print("Found", len(vms), "VM entries")
    # POST each VM to controller
    for vm in vms:
        payload = {
            "vm_uuid": vm.get("uuid"),
            "name": vm.get("name-label"),
            "host_id": vm.get("resident-on"),
            "state": vm.get("power-state"),
        }
        try:
            resp = requests.post(f"{CONTROLLER_URL.rstrip('/')}/vms/register", json=payload, headers=HEADERS, timeout=10)
            if resp.status_code not in (200,201,202):
                print("Failed to register:", payload["vm_uuid"], "status", resp.status_code, resp.text)
            else:
                print("Registered:", payload["vm_uuid"], "->", resp.json())
        except Exception as e:
            print("Error posting to controller:", e)

if __name__ == "__main__":
    main()
