# scheduler/policies.py
from typing import Dict, List, Optional
from .config import W_CPU, W_MEM, W_LOAD, LOW_CPU_THRESHOLD, LOW_MEM_THRESHOLD, HIGH_CPU_THRESHOLD, HIGH_MEM_THRESHOLD
from .models import Host, VM

def host_score(h: Host) -> float:
    cpu_norm = (h.cpu_percent or 0.0) / 100.0
    mem_norm = (h.mem_percent or 0.0) / 100.0
    load_norm = (h.load1 or 0.0) / max(1.0, getattr(h, "cpu_count", 1))
    return W_CPU * cpu_norm + W_MEM * mem_norm + W_LOAD * load_norm

def is_host_overloaded(h: Host) -> bool:
    return (h.cpu_percent or 0.0) >= HIGH_CPU_THRESHOLD or (h.mem_percent or 0.0) >= HIGH_MEM_THRESHOLD

def can_receive_vm(h: Host, vm_cpu_percent_est: float, vm_mem_percent_est: float = 0.0) -> bool:
    projected_cpu = (h.cpu_percent or 0.0) + vm_cpu_percent_est
    projected_mem = (h.mem_percent or 0.0) + vm_mem_percent_est
    if projected_cpu >= LOW_CPU_THRESHOLD: return False
    if projected_mem >= LOW_MEM_THRESHOLD: return False
    if h.status and h.status.upper() != "UP": return False
    return True

def select_best_destination(hosts: List[Host], vm_cpu_est: float, exclude_host_id: Optional[str] = None) -> Optional[Host]:
    candidates = []
    for h in hosts:
        if exclude_host_id and h.host_id == exclude_host_id:
            continue
        if not can_receive_vm(h, vm_cpu_est):
            continue
        candidates.append((host_score(h), h))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]
