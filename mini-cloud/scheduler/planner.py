# scheduler/planner.py
import time
from typing import List, Tuple, Dict
from .models import Host, VM
from .policies import select_best_destination, is_host_overloaded
from .config import MAX_CONCURRENT_MIGRATIONS, MAX_EMERGENCY_MIGRATIONS_PER_HOST, MIGRATION_COOLDOWN, HOST_COOLDOWN

class Planner:
    def __init__(self):
        # in-memory cooldown trackers; simple but effective for a first implementation
        self.vm_cooldowns = {}  # vm_uuid -> timestamp when cooldown expires
        self.host_cooldowns = {}  # host_id -> timestamp when cooldown expires
        self.emergency_migrations_per_host = {}  # host_id -> count in current window

    def in_vm_cooldown(self, vm: VM) -> bool:
        t = self.vm_cooldowns.get(vm.vm_uuid)
        return t and t > time.time()

    def set_vm_cooldown(self, vm: VM):
        self.vm_cooldowns[vm.vm_uuid] = time.time() + MIGRATION_COOLDOWN

    def in_host_cooldown(self, host_id: str) -> bool:
        t = self.host_cooldowns.get(host_id)
        return t and t > time.time()

    def set_host_cooldown(self, host_id: str):
        self.host_cooldowns[host_id] = time.time() + HOST_COOLDOWN

    def plan_rebalance(self, hosts: List[Host], vms_by_host: Dict[str, List[VM]], max_plan: int = 5) -> List[Tuple[VM, str]]:
        """
        returns list of (vm, dst_host_id) proposals for periodic rebalance.
        conservative: at most max_plan migrations.
        """
        plan = []
        # sort overloaded hosts by descending cpu to prioritize worst offenders
        overloaded = [h for h in hosts if is_host_overloaded(h) and not self.in_host_cooldown(h.host_id)]
        overloaded.sort(key=lambda h: h.cpu_percent, reverse=True)
        # sort healthy destinations by score ascending
        healthy = sorted(hosts, key=lambda h: h.host_id)  # score selection handled when choosing dst
        for src in overloaded:
            vms = vms_by_host.get(src.host_id, [])
            # choose candidate VMs - prefer largest cpu% first
            vms_sorted = sorted([vm for vm in vms if not self.in_vm_cooldown(vm) and not vm.protected],
                                key=lambda v: v.cpu_percent or 0.0, reverse=True)
            for vm in vms_sorted:
                dst = select_best_destination(healthy, vm_cpu_est=vm.cpu_percent or 0.0, exclude_host_id=src.host_id)
                if dst:
                    plan.append((vm, dst.host_id))
                    self.set_vm_cooldown(vm)
                    self.set_host_cooldown(src.host_id)
                    # update simulated resources in src/dst for subsequent planning - naive
                    src.cpu_percent = max(0.0, (src.cpu_percent or 0.0) - (vm.cpu_percent or 0.0))
                    dst.cpu_percent = (dst.cpu_percent or 0.0) + (vm.cpu_percent or 0.0)
                if len(plan) >= max_plan:
                    return plan
        return plan

    def plan_emergency(self, alert_host: Host, hosts: List[Host], vms: List[VM]) -> List[Tuple[VM, str]]:
        """
        Focused, fast plan: pick the heaviest VM and move it once if possible.
        """
        host_id = alert_host.host_id
        if self.in_host_cooldown(host_id):
            return []
        # ensure we don't propose too many emergency migrations for the host
        count = self.emergency_migrations_per_host.get(host_id, 0)
        if count >= MAX_EMERGENCY_MIGRATIONS_PER_HOST:
            return []

        candidates = [vm for vm in vms if not vm.protected and not self.in_vm_cooldown(vm)]
        candidates.sort(key=lambda v: v.cpu_percent or 0.0, reverse=True)
        for vm in candidates[:3]:
            dst = select_best_destination(hosts, vm_cpu_est=vm.cpu_percent or 0.0, exclude_host_id=host_id)
            if dst:
                # propose single migration
                self.set_vm_cooldown(vm)
                self.set_host_cooldown(host_id)
                self.emergency_migrations_per_host[host_id] = count + 1
                return [(vm, dst.host_id)]
        # no dest
        return []
