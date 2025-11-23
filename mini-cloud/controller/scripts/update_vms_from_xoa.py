#!/usr/bin/env python3
# controller/scripts/update_vms_from_xoa.py
# Usage: cd controller && source .venv/bin/activate && python scripts/update_vms_from_xoa.py

import json
from app.db import SessionLocal
from app.models import VM, Host
from app.xoa_client import get_xoa_rest_client

def to_int_mb(bytes_val):
    try:
        b = int(bytes_val)
        return max(1, b // (1024*1024))
    except Exception:
        return None

def guess_ip(vm):
    # as before: try guest_metrics.networks then networks fields
    gm = vm.get("guest_metrics") or {}
    if isinstance(gm, dict):
        nets = gm.get("networks")
        if isinstance(nets, dict):
            for _, v in nets.items():
                if v and isinstance(v, str) and "." in v:
                    return v
    networks = vm.get("networks") or vm.get("networks0")
    if isinstance(networks, dict):
        for _, v in networks.items():
            if v and isinstance(v, str) and "." in v:
                return v
    return None

def main():
    client = get_xoa_rest_client()
    session = SessionLocal()
    try:
        rows = session.query(VM).all()
        if not rows:
            print("No VMs in DB to update.")
            return
        for vm_row in rows:
            xen = vm_row.xen_uuid
            if not xen:
                print("Skipping DB row with no xen_uuid, id=", vm_row.id)
                continue
            try:
                xoa_vm = client.get_vm(xen)  # fetch full JSON
            except Exception as e:
                print("Failed to fetch XOA VM for", xen, ":", e)
                continue

            # extract host id (look for $container or resident_on)
            host_id = None
            if isinstance(xoa_vm.get("$container"), str):
                host_id = xoa_vm.get("$container")
            else:
                res = xoa_vm.get("resident_on") or xoa_vm.get("resident_on_ref") or xoa_vm.get("host")
                if isinstance(res, dict):
                    host_id = res.get("uuid") or res.get("id")
                elif isinstance(res, str):
                    host_id = res.split("/")[-1]

            # CPUs
            vcpu = None
            cpus = xoa_vm.get("CPUs") or {}
            if isinstance(cpus, dict):
                vcpu = cpus.get("number") or cpus.get("max")

            # memory: prefer memory.size if present (bytes)
            mem_mb = None
            mem = xoa_vm.get("memory") or {}
            if isinstance(mem, dict):
                # 'size' is present in your example
                if "size" in mem:
                    mem_mb = to_int_mb(mem["size"])
                elif "static" in mem and isinstance(mem["static"], (list,tuple)):
                    # use second static value if present
                    try:
                        mem_mb = to_int_mb(mem["static"][-1])
                    except Exception:
                        pass
            # fallback fields
            if mem_mb is None:
                if xoa_vm.get("memory_mb"):
                    try:
                        mem_mb = int(xoa_vm.get("memory_mb"))
                    except Exception:
                        pass

            # state
            state = xoa_vm.get("power_state") or xoa_vm.get("state") or vm_row.state

            # ip
            ip = guess_ip(xoa_vm)

            # apply updates if changed / missing
            changed = False
            if host_id and (vm_row.host_id is None or str(vm_row.host_id) != str(host_id)):
                vm_row.host_id = host_id
                changed = True
            if vcpu and (not vm_row.vcpu or vm_row.vcpu != int(vcpu)):
                vm_row.vcpu = int(vcpu)
                changed = True
            if mem_mb and (not vm_row.memory_mb or vm_row.memory_mb != int(mem_mb)):
                vm_row.memory_mb = int(mem_mb)
                changed = True
            if state and (not vm_row.state or vm_row.state != state):
                vm_row.state = state
                changed = True
            if ip and (not vm_row.ip or vm_row.ip != ip):
                vm_row.ip = ip
                changed = True

            if changed:
                try:
                    session.add(vm_row)
                    session.commit()
                    print("Updated", xen, "host=", host_id, "vcpu=", vcpu, "mem_mb=", mem_mb, "state=", state, "ip=", ip)
                except Exception as e:
                    session.rollback()
                    print("DB update failed for", xen, ":", e)
            else:
                print("No update needed for", xen)

    finally:
        session.close()

if __name__ == "__main__":
    main()
