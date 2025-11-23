# app/migration_service/clients/xen_ssh_client.py
from app.migration_service.utils import ssh_run
import json
import time

class XenSSHClient:
    def __init__(self, host, user="root", ssh_timeout=60):
        self.host = host
        self.user = user
        self.timeout = ssh_timeout

    def _xe(self, cmd):
        # Use --minimal output where possible; command string must be quoted
        full_cmd = f"xe {cmd}"
        rc, out, err = ssh_run(self.host, self.user, full_cmd, timeout=self.timeout)
        return rc, out, err

    def sr_shared(self, sr_uuid):
        rc, out, err = self._xe(f"sr-list uuid={sr_uuid} params=uuid,shared,other-config --minimal")
        if rc != 0:
            raise RuntimeError(f"xe sr-list failed: {err or out}")
        # parse output lines like: uuid:..., shared (RW): false
        # simplest approach: call sr-list with params and parse key: value lines
        rc, out, err = self._xe(f"sr-list uuid={sr_uuid} params=shared,other-config")
        if rc != 0:
            raise RuntimeError(f"xe sr-list failed: {err or out}")
        shared = "false"
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("shared"):
                # e.g. shared ( RW): false
                if ":" in line:
                    shared = line.split(":")[-1].strip()
        return shared.lower() == "true"

    def set_sr_shared(self, sr_uuid, value=True):
        val = "true" if value else "false"
        rc, out, err = self._xe(f"sr-param-set uuid={sr_uuid} shared={val}")
        if rc != 0:
            raise RuntimeError(f"xe sr-param-set failed: {err or out}")
        return True

    def pbd_list(self, sr_uuid):
        rc, out, err = self._xe(f"pbd-list sr-uuid={sr_uuid} params=uuid,host-uuid,device-config,currently-attached")
        if rc != 0:
            raise RuntimeError(f"xe pbd-list failed: {err or out}")
        return out

    def vm_resident_on(self, vm_uuid):
        rc, out, err = self._xe(f"vm-list uuid={vm_uuid} params=resident-on --minimal")
        if rc != 0:
            raise RuntimeError(f"xe vm-list resident-on failed: {err or out}")
        # parse resident-on uuid from output
        rc, out, err = self._xe(f"vm-list uuid={vm_uuid} params=resident-on")
        if rc != 0:
            raise RuntimeError(f"xe vm-list failed: {err or out}")
        for line in out.splitlines():
            if line.strip().startswith("resident-on"):
                return line.split(":")[-1].strip()
        return None

    def vm_migrate_live(self, vm_uuid, target_host_uuid):
        rc, out, err = self._xe(f"vm-migrate vm={vm_uuid} host={target_host_uuid} live=true")
        # Note: successful migrate returns empty output with rc 0.
        return rc, out, err
    
    def vm_get_params(self, vm_uuid, params_list):
        """
        Return a dict of requested params for the VM (params_list e.g. ['HVM-boot-policy','platform','power-state','other-config'])
        """
        # build params string
        params = ",".join(params_list)
        rc, out, err = self._xe(f"vm-list uuid={vm_uuid} params={params}")
        if rc != 0:
            raise RuntimeError(f"xe vm-list failed: {err or out}")
        # parse simple key: value lines of the returned block (we assume single VM block)
        record = {}
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if not line:
                if current:
                    # first block complete
                    break
            else:
                if ":" in line:
                    key, val = line.split(":", 1)
                    record[key.strip()] = val.strip()
        # post-process platform and other-config: they often appear as maps, but here we'll return raw strings for simplicity
        # return requested keys if present
        result = {}
        for p in params_list:
            # some responses call 'HVM-boot-policy' or 'HVM-boot-policy (RO)' — we search keys by startswith
            for k, v in record.items():
                if k.startswith(p):
                    result[p] = v
                    break
            else:
                result[p] = None
        return result
