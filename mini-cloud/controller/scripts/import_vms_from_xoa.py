#!/usr/bin/env python3
# controller/scripts/import_vms_from_xoa.py
# Run from controller dir with venv activated:
# python scripts/import_vms_from_xoa.py

import sys
import uuid
import json
from typing import Any, Optional
from app.db import SessionLocal
from app.models import VM, Host
from app.xoa_client import get_xoa_rest_client

def safe_int(value: Any, fallback: int = 0) -> int:
    """
    Try to coerce a value into int. Handles:
      - int/float
      - numeric strings
      - dicts containing obvious numeric fields like {'value': 1024} or {'amount': '1024'}
      - lists (take first element if scalar)
    Returns fallback on failure.
    """
    if value is None:
        return fallback
    # direct ints/floats
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    # numeric strings
    if isinstance(value, str):
        try:
            # strip non-numeric extras
            s = value.strip()
            # sometimes values like "1024 bytes" appear — take leading number
            num = ''
            for ch in s:
                if ch.isdigit() or ch in "-.":
                    num += ch
                else:
                    break
            return int(float(num)) if num else fallback
        except Exception:
            return fallback
    # dicts: try common keys
    if isinstance(value, dict):
        for key in ("value", "amount", "size", "memory", "count", "max", "VCPUs_max", "VCPUs"):
            if key in value:
                return safe_int(value[key], fallback)
        # nested single-key dicts: try first value
        try:
            first = next(iter(value.values()))
            return safe_int(first, fallback)
        except Exception:
            return fallback
    # lists: try the first element
    if isinstance(value, (list, tuple)) and value:
        return safe_int(value[0], fallback)
    # unknown -> fallback
    return fallback

def safe_str(value: Any, fallback: Optional[str] = None) -> Optional[str]:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        # try common fields
        for key in ("name_label", "name", "label", "uuid"):
            if key in value:
                return safe_str(value[key], fallback)
        try:
            return safe_str(next(iter(value.values())), fallback)
        except Exception:
            return fallback
    if isinstance(value, (list, tuple)) and value:
        return safe_str(value[0], fallback)
    return fallback

def guess_ip_from_vm(vm: dict) -> Optional[str]:
    ip = None
    gm = vm.get("guest_metrics") or {}
    nets = None
    if isinstance(gm, dict):
        nets = gm.get("networks")
    if isinstance(nets, dict):
        for _, v in nets.items():
            if v and isinstance(v, str) and "." in v:
                ip = v
                break
    if not ip:
        networks = vm.get("networks") or vm.get("networks0")
        if isinstance(networks, dict):
            for _, v in networks.items():
                if v and isinstance(v, str) and "." in v:
                    ip = v
                    break
    if not ip:
        ip = vm.get("ip") or vm.get("ipv4")
    return ip

def fetch_full_vm(client, vm_item):
    if isinstance(vm_item, dict):
        return vm_item
    if isinstance(vm_item, str):
        try:
            return client.get_vm(vm_item)
        except Exception as e:
            print("failed to fetch vm detail for", vm_item, ":", e)
            return None
    return None

def first_existing(*args):
    for a in args:
        if a is not None:
            return a
    return None

def extract_vcpu(vm: dict) -> int:
    # try several candidate fields that XOA might return
    candidates = [
        vm.get("VCPUs_max"),
        vm.get("VCPUs"),
        vm.get("vcpus"),
        vm.get("VCPUs_at_startup"),
        vm.get("cpu_count"),
        vm.get("cpu"),
    ]
    # also look into nested guest_metrics possibly
    gm = vm.get("guest_metrics") or {}
    if isinstance(gm, dict):
        candidates.append(gm.get("vcpus") if gm.get("vcpus") is not None else None)
    for c in candidates:
        val = safe_int(c, None)
        if val:
            return val
    return 1

def extract_memory_mb(vm: dict) -> int:
    candidates = [
        vm.get("memory_static_max"),
        vm.get("memory_static_min"),
        vm.get("memory"),
        vm.get("memory_mb"),
        vm.get("memory_max"),
        vm.get("memory_size"),
    ]
    gm = vm.get("guest_metrics") or {}
    if isinstance(gm, dict):
        # sometimes memory is under guest_metrics.memory/ram
        candidates.append(gm.get("memory"))
    for c in candidates:
        val = safe_int(c, None)
        if val:
            # some fields may be bytes, detect large values > 10000 meaning bytes, convert to MB
            if val > 100000:  # rough heuristic: >100k likely bytes
                return max(1, val // (1024*1024))
            # if value looks like MB already
            return val
    return 512

def extract_state(vm: dict) -> str:
    s = first_existing(vm.get("power_state"), vm.get("state"), vm.get("status"))
    return safe_str(s, "running") or "running"

def main():
    session = SessionLocal()
    try:
        client = get_xoa_rest_client()
        raw_vms = client._get("/vms")
        if not raw_vms:
            print("No VMs returned from XOA.")
            return

        print(f"XOA returned {len(raw_vms)} items. Processing...")

        for item in raw_vms:
            vm = fetch_full_vm(client, item)
            if not vm:
                print("Skipping invalid VM item:", item)
                continue

            xen_uuid = safe_str(vm.get("uuid") or vm.get("id") or vm.get("ref"))
            name = safe_str(vm.get("name_label") or vm.get("name") or vm.get("label") or "vm-unknown")

            # skip XOA appliance by name (case-insensitive)
            if name and name.lower().startswith("xoa"):
                print("Skipping XOA appliance VM:", name, xen_uuid)
                continue

            # host resolution
            host_obj = None
            resident = vm.get("resident_on") or vm.get("resident_on_ref") or vm.get("host")
            if resident:
                host_uuid = None
                host_name = None
                if isinstance(resident, dict):
                    host_uuid = safe_str(resident.get("uuid") or resident.get("id"))
                    host_name = safe_str(resident.get("name_label") or resident.get("name"))
                else:
                    host_uuid = safe_str(resident)
                if host_uuid:
                    h = session.query(Host).filter(Host.id == host_uuid).first()
                    if h:
                        host_obj = h
                    else:
                        # try extract uuid from path-like strings
                        try:
                            maybe_uuid = host_uuid.split("/")[-1]
                            h2 = session.query(Host).filter(Host.id == maybe_uuid).first()
                            if h2:
                                host_obj = h2
                        except Exception:
                            pass
                if not host_obj and host_name:
                    host_obj = session.query(Host).filter(Host.name == host_name).first()

            # extract numeric and state fields safely
            vcpu = extract_vcpu(vm)
            memory_mb = extract_memory_mb(vm)
            state = extract_state(vm)
            ip = guess_ip_from_vm(vm)

            if not xen_uuid:
                print("Skipping VM without xen_uuid (unexpected):", json.dumps(vm)[:400])
                continue

            exists = session.query(VM).filter(VM.xen_uuid == xen_uuid).first()
            if exists:
                updated = False
                if exists.host_id is None and host_obj:
                    exists.host_id = host_obj.id; updated = True
                if (not exists.vcpu or exists.vcpu == 0) and vcpu:
                    exists.vcpu = int(vcpu); updated = True
                if (not exists.memory_mb or exists.memory_mb == 0) and memory_mb:
                    exists.memory_mb = int(memory_mb); updated = True
                if (not exists.state or (exists.state and exists.state.lower() != state.lower())):
                    exists.state = state; updated = True
                if (not exists.ip) and ip:
                    exists.ip = ip; updated = True
                if updated:
                    try:
                        session.add(exists)
                        session.commit()
                        print("Updated VM:", name, xen_uuid)
                    except Exception as ex:
                        session.rollback()
                        print("Failed to update VM", name, xen_uuid, ":", ex)
                else:
                    print("Already exists (skipping):", name, xen_uuid)
                continue

            # create VM row with safe values
            try:
                new_vm = VM(
                    id=uuid.uuid4(),
                    name=name,
                    xen_uuid=xen_uuid,
                    host_id=host_obj.id if host_obj else None,
                    vcpu=int(vcpu) if vcpu else 1,
                    memory_mb=int(memory_mb) if memory_mb else 512,
                    state=state,
                    ip=ip,
                )
                session.add(new_vm)
                session.commit()
                print("Inserted VM:", name, xen_uuid, "host:", host_obj.name if host_obj else None)
            except Exception as ex:
                session.rollback()
                print("Failed to insert VM", name, xen_uuid, ":", ex)

    finally:
        session.close()

if __name__ == "__main__":
    main()
