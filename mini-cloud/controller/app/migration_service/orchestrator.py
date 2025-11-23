# app/migration_service/orchestrator.py
import time
from app.migration_service.clients.xen_ssh_client import XenSSHClient

class MigrationOrchestrator:
    def __init__(self, ssh_host_for_xe, ssh_user="root", logger=None):
        self.client = XenSSHClient(ssh_host_for_xe, user=ssh_user)
        self.log = logger or (lambda *a, **k: None)

    def ensure_sr_and_pbd_for_vm(self, sr_uuid, target_host_uuid, nfs_server, nfs_export):
        # ensure SR is shared if NFS
        if not self.client.sr_shared(sr_uuid):
            self.log("SR not shared; setting shared=true")
            # safe to set if type is NFS and other-config empty (we assume it's NFS here)
            self.client.set_sr_shared(sr_uuid, True)

        # Ensure target host has PBD attached:
        # We'll run the idempotent attach script on the pool master (self.client.host)
        cmd = f"/root/mini-cloud/controller/app/migration_service/idempotent-attach-pbd.sh {sr_uuid} {target_host_uuid} {nfs_server} {nfs_export}"
        rc, out, err = self.client._xe(f"bash -lc \"{cmd}\"")  # run via ssh-run through _xe wrapper
        if rc != 0:
            raise RuntimeError(f"PBD attach failed: {err or out}")

    def run_live_migration(self, vm_uuid, target_host_uuid, poll_interval=2, timeout=300):
        rc, out, err = self.client.vm_migrate_live(vm_uuid, target_host_uuid)
        if rc != 0:
            raise RuntimeError(f"vm-migrate failed: {err or out}")
        # poll until resident-on changes
        start = time.time()
        while time.time() - start < timeout:
            resident = self.client.vm_resident_on(vm_uuid)
            if resident and resident.strip() == target_host_uuid:
                return True
            time.sleep(poll_interval)
        raise TimeoutError("Migration did not complete in time")
    
    def is_live_migratable(self, vm_uuid):
        """
        Conservative auto-detection: True if VM either has the guest_tools flag
        or appears to be PV/PVHVM with PV drivers (HVM-boot-policy empty OR
        platform shows PV support). Returns (True, reason) or (False, reason).
        """
        # 1) Check other_config flag quickly (if migration record passed in, could use that)
        try:
            # try via session-based migration record first if available
            # otherwise use xen_ssh client
            # Using XenSSHClient:
            params = self.client.vm_get_params(vm_uuid, ["other-config", "HVM-boot-policy", "platform", "power-state"])
        except Exception as e:
            return False, f"vm param fetch failed: {e}"

        # check power-state
        ps = params.get("power-state") or params.get("power-state ( RO)") or ""
        if ps and ps.lower() != "running":
            return False, f"VM power-state is not running: {ps}"

        # other-config parsing
        oc_raw = params.get("other-config") or ""
        try:
            # try to find a guest flag inside the raw string
            if "guest_tools_installed" in oc_raw and "true" in oc_raw:
                return True, "guest_tools_installed flag present"
            # sometimes XO stores keys with prefixes (xo:...), check
            if "guest_tools_installed" in oc_raw:
                # still assume true if present
                return True, "guest_tools_installed key present in other-config"
        except Exception:
            pass

        # HVM-boot-policy heuristic: empty or not set -> likely PV/PVHVM with PV drivers
        hvm_policy = params.get("HVM-boot-policy") or params.get("HVM-boot-policy ( RO)") or ""
        if not hvm_policy:
            return True, "HVM-boot-policy empty => PV/PVHVM likely, allow live migrate"

        # platform heuristic: look for PV-related entries in the platform map string
        plat_raw = params.get("platform") or ""
        plat_l = plat_raw.lower() if isinstance(plat_raw, str) else ""
        # a few common substrings that indicate PV-friendly platform entries:
        for marker in ("xen_platform", "pvdrivers", "pv", "hvm-boot-policy", "xen"):
            if marker in plat_l:
                return True, f"platform contains PV marker '{marker}' => allow"

        # otherwise conservative block
        return False, f"HVM policy present and platform not indicating PV support (hvm_policy='{hvm_policy}', platform='{plat_raw[:200]}')"
