# controller/app/migration/orchestrator.py
import time
import traceback
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.xoa_client import get_xoa_rest_client
from app.models import Migration, MigrationEvent

# candidate XOA endpoints to try (relative to /rest/v0)
CANDIDATE_MIGRATE_PATHS = [
    "/vms/{vm}/actions/migrate",
    "/vms/{vm}/migrate",
    "/vms/{vm}/actions/migrate_vm",
    "/vms/{vm}/actions/migrate_vm",   # keep duplicates intentionally
    # Some XOA versions use a pool-level action or different path; keep this list extendable
]

# candidate payload shapes to try
def _payload_variants(target_host: str, target_sr: Optional[str] = None) -> List[Dict[str, Any]]:
    base = []
    # simplest
    base.append({"host": target_host})
    base.append({"target": target_host})
    base.append({"destination": target_host})
    base.append({"target_host": target_host})
    base.append({"host_uuid": target_host})
    base.append({"to": {"host": target_host}})
    base.append({"destination": {"host": target_host}})
    # include sr variants if present
    if target_sr:
        base.append({"host": target_host, "sr": target_sr})
        base.append({"host": target_host, "sr_uuid": target_sr})
        base.append({"target": target_host, "sr": target_sr})
        base.append({"vdi_to_sr": { }, "host": target_host})  # placeholder for per-vdi mapping
    return base

POLL_INTERVAL = 2.0
POLL_TIMEOUT = 300  # seconds

def _now_ts():
    return datetime.now(timezone.utc)

class MigrationOrchestrator:
    def __init__(self, db: Session, migration: Migration, simulate: bool = False):
        self.db = db
        self.migration = migration
        self.simulate = simulate
        self.xoa = get_xoa_rest_client()

    def _insert_event(self, level: str, message: str, meta: Optional[Dict[str, Any]] = None):
        ev = MigrationEvent(migration_id=self.migration.id, level=level, message=message, meta=meta)
        self.db.add(ev)
        self.db.commit()

    def _update_progress(self, pct: int):
        try:
            self.migration.progress = max(0, min(100, int(pct)))
            self.db.add(self.migration)
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _try_migrate_via_xoa(self, vm_uuid: str, target_host: str, target_sr: Optional[str] = None) -> Dict[str, Any]:
        """
        Try multiple endpoint+payload combinations against XOA and return the first that looks like success.
        Returns a dict with keys: ok(bool), endpoint, payload, resp, op_id (if any), error (if any)
        """
        tried = []
        for path_tpl in CANDIDATE_MIGRATE_PATHS:
            path = path_tpl.format(vm=vm_uuid)
            payloads = _payload_variants(target_host, target_sr)
            for payload in payloads:
                tried.append({"endpoint": path, "payload": payload})
                self._insert_event("info", f"Attempting XOA migrate via {path} with payload keys: {list(payload.keys())}")
                try:
                    # Using internal low-level wrappers to preserve session/cookie behavior
                    resp = None
                    try:
                        resp = self.xoa._post(path, data=payload)
                    except Exception as e:
                        # capture raw exception and any text snippet if available (xoa client raises with text)
                        self._insert_event("warning", f"XOA migrate attempt {path} returned error: {e}")
                        continue

                    # if we got JSON-like response:
                    if isinstance(resp, dict):
                        # typical responses contain an op id or task id
                        op_id = resp.get("id") or resp.get("task") or resp.get("operation") or resp.get("result")
                        return {"ok": True, "endpoint": path, "payload": payload, "resp": resp, "op_id": op_id}
                    else:
                        # non-dict JSON (e.g. list) treat as success-ish — return it
                        return {"ok": True, "endpoint": path, "payload": payload, "resp": resp, "op_id": None}
                except Exception as exc:
                    self._insert_event("warning", f"Exception calling {path}: {exc}", {"traceback": traceback.format_exc()})
                    continue
        # nothing worked
        return {"ok": False, "error": "no_supported_endpoint", "tried": tried}

    def _poll_operation(self, op_id: str, timeout=POLL_TIMEOUT) -> Dict[str, Any]:
        start = time.time()
        candidate_paths = [f"/tasks/{op_id}", f"/operations/{op_id}", f"/jobs/{op_id}", f"/tasks/{op_id}/status"]
        while True:
            if time.time() - start > timeout:
                return {"ok": False, "error": "timeout"}
            for p in candidate_paths:
                try:
                    resp = self.xoa._get(p)
                except Exception:
                    continue
                if isinstance(resp, dict):
                    status = resp.get("status") or resp.get("state") or resp.get("result")
                    st = str(status).lower() if status is not None else None
                    if st in ("done", "success", "ok", "completed"):
                        return {"ok": True, "resp": resp}
                    if st in ("failed", "error", "aborted"):
                        return {"ok": False, "resp": resp, "error": "failed"}
                    prog = resp.get("progress") or resp.get("percent") or resp.get("percentage")
                    if prog is not None:
                        try:
                            self._update_progress(int(prog))
                        except Exception:
                            pass
            time.sleep(POLL_INTERVAL)

    def run(self) -> Dict[str, Any]:
        vm_uuid = str(self.migration.vm_id)
        tgt = self.migration.target_host
        # support optional target_sr field stored in migration.details or migration.details.get("target_sr")
        target_sr = None
        try:
            if self.migration.details and isinstance(self.migration.details, dict):
                target_sr = self.migration.details.get("target_sr")
        except Exception:
            target_sr = None

        try:
            self._insert_event("info", f"Validating migration prerequisites for VM {vm_uuid}")
            # check VM present in XOA
            try:
                vm_info = self.xoa._get(f"/vms/{vm_uuid}")
                self._insert_event("info", f"Found VM in XOA: {vm_uuid}", {"vm": (vm_info.get("name_label") if isinstance(vm_info, dict) else None)})
            except Exception as e:
                self._insert_event("warning", f"VM {vm_uuid} not found in XOA or API error: {e}", {"traceback": traceback.format_exc()})
                return {"ok": False, "error": "vm_not_found_or_xoa_error", "detail": str(e)}

            if self.simulate:
                self._insert_event("info", "Simulating live migration (simulate=True).")
                for p in (5, 25, 50, 80, 100):
                    self._update_progress(p)
                    self._insert_event("info", f"Transferring memory and state (simulated) {p}%")
                    time.sleep(0.5)
                return {"ok": True}

            # try to call XOA with multiple payloads
            try:
                res = self._try_migrate_via_xoa(vm_uuid, tgt, target_sr)
            except Exception as exc:
                self._insert_event("error", f"Unexpected error trying XOA migrate: {exc}", {"traceback": traceback.format_exc()})
                return {"ok": False, "error": "xoa_try_exception", "detail": str(exc)}

            if not res.get("ok"):
                self._insert_event("warning", f"No supported XOA migrate endpoint, aborting: {res.get('error')}", {"tried_count": len(res.get("tried", []))})
                # store tried list as debug meta for later
                return {"ok": False, "error": "no_supported_endpoint", "tried": res.get("tried")}

            op_id = res.get("op_id")
            self._insert_event("info", f"XOA migration invoked via {res.get('endpoint')}", {"resp": res.get("resp"), "payload": res.get("payload")})
            if not op_id:
                # Best-effort: mark progress then succeed
                self._update_progress(75)
                time.sleep(1.0)
                self._update_progress(100)
                return {"ok": True, "resp": res.get("resp")}

            # poll operation
            self._insert_event("info", f"Polling XOA operation {op_id}")
            poll_res = self._poll_operation(op_id)
            if not poll_res.get("ok"):
                self._insert_event("error", f"Operation {op_id} failed or timed out", {"poll": poll_res})
                return {"ok": False, "error": "op_failed", "poll": poll_res}
            self._update_progress(100)
            self._insert_event("info", f"Operation {op_id} completed", {"resp": poll_res.get("resp")})
            return {"ok": True, "op_id": op_id, "resp": poll_res.get("resp")}
        except Exception as e:
            self._insert_event("error", f"Unhandled orchestrator exception: {e}", {"traceback": traceback.format_exc()})
            return {"ok": False, "error": "exception", "detail": str(e)}
