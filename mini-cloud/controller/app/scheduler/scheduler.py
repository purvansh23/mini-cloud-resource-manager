# app/scheduler.py
import subprocess
import shlex
import random
import logging
import time
from typing import Optional, Dict, Any

from app import models
from app.metrics_utils import calculate_host_score
from app.db import SessionLocal

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------ Host helpers ------------------

def host_is_overloaded(latest_metric) -> bool:
    """
    Simple threshold check for overloaded host.
    Matches checks described in the PDF final code.
    """
    try:
        cpu = float(latest_metric.cpu_percent or 0)
        mem = float(latest_metric.mem_percent or 0)
    except Exception:
        return False

    if cpu > 80.0 or mem > 85.0:
        return True
    return False


def select_least_loaded_host(db) -> models.Host:
    """
    Return the best host according to the final scoring logic.
    Uses calculate_host_score on the latest HostMetric of each host.
    """
    hosts = db.query(models.Host).all()
    if not hosts:
        raise RuntimeError("No hosts configured in DB")

    selected = []

    logger.info("\n==================== SCHEDULER START ====================\n")

    for host in hosts:
        if not host.metrics:
            logger.info(f"[NO METRICS] Skipping host {host.name}")
            continue

        latest = sorted(host.metrics, key=lambda m: m.ts)[-1]
        if host_is_overloaded(latest):
            logger.info(
                f"[SKIP] Host {host.name} overloaded "
                f"CPU={latest.cpu_percent:.2f}%, MEM={latest.mem_percent:.2f}%"
            )
            continue

        comp = calculate_host_score(latest)

        logger.info(
            f"[SCHEDULER][HOST: {host.name}] CPU_raw={latest.cpu_percent:.2f}% "
            f"-> cpu_norm={comp['cpu_norm']:.3f} "
            f" MEM_raw={latest.mem_percent:.2f}% -> mem_norm={comp['mem_norm']:.3f} "
            f" VM_count_raw={latest.vms_running} -> vmc_norm={comp['vmc_norm']:.3f} "
            f" FINAL SCORE={comp['score']:.5f}"
        )

        selected.append((comp["score"], host))

    if not selected:
        raise RuntimeError("No host is available under caps")

    # Sort ascending (lower score = less loaded)
    selected.sort(key=lambda x: x[0])

    # Handle near-tie with small randomization
    if len(selected) > 1 and abs(selected[0][0] - selected[1][0]) < 0.05:
        best = random.choice(selected[:2])[1]
    else:
        best = selected[0][1]

    logger.info(
        f"\n[SELECTED HOST] {best.name} (UUID={best.uuid_xen}, IP={best.ip})"
    )
    logger.info("==================== SCHEDULER END =====================\n")

    return best


# ------------------ VM creation / scheduling ------------------

def schedule_vm_custom(
    db,
    user_cfg: Dict[str, Any],
    template_name: str,
    pool_id: str,
    script_path: str = "/app/app/create_vm_remote_fixed.sh"
) -> Dict[str, Any]:
    """
    Main scheduler entrypoint used by API.
    - selects the best host
    - builds command for remote creation script
    - executes the script
    - records VM in DB
    """

    # 1) Pick host
    best = select_least_loaded_host(db)

    logger.info(
        f"[Scheduler] Selected host: {best.name} ({best.uuid_xen}) ip={best.ip}"
    )

    vm_name = user_cfg.get("name", f"Auto-VM-{best.name}")
    vcpus = int(user_cfg.get("vcpus", 1))
    ram = int(user_cfg.get("ram", 512))
    disk_gib = int(user_cfg.get("disk", 10))
    disk = f"{disk_gib} GiB"
    network = user_cfg.get("network", "")
    ssh_key = user_cfg.get("ssh_key", "/root/.ssh/id_rsa.pub")

    if not best.ip:
        raise RuntimeError("Selected host has no registered IP")

    # 2) Build command
    args = [
        script_path,
        "--host", str(best.ip),
        "--name", vm_name,
        "--template", template_name,
        "--cpu", str(vcpus),
        "--ram", str(ram),
        "--disk", disk,
        "--network", network,
        "--ssh-key", ssh_key,
    ]

    safe_cmd = " ".join(shlex.quote(a) for a in args)
    logger.info(f"[Scheduler] EXECUTING: {safe_cmd}")

    # 3) Run script
    try:
        proc = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = proc.stdout or ""
        logger.info(f"[Scheduler] Script finished. Output:\n{output}")

    except subprocess.CalledProcessError as e:
        output = e.output if hasattr(e, "output") else str(e)
        logger.exception(f"[Scheduler] VM creation script failed: {output}")
        raise

    # 4) Parse output
    vm_uuid = None
    vm_ip = None

    for line in (output or "").splitlines():
        if "UUID" in line:
            try:
                vm_uuid = line.split("UUID")[1].split(":")[1].strip()
            except Exception:
                pass
        if "IP" in line:
            try:
                vm_ip = line.split("IP")[1].split(":")[1].strip()
            except Exception:
                pass

    # 5) Save VM to DB (best-effort)
    vm_record = None
    try:
        vm_record = models.VM(
            name=vm_name,
            uuid=vm_uuid or "",
            host_id=best.id,
            ip=vm_ip or None,
            memory_mb=ram,
            vcpus=vcpus,
            created_at=int(time.time())
        )
        db.add(vm_record)
        db.commit()
        db.refresh(vm_record)
        logger.info(
            f"[Scheduler] VM record created in DB id={vm_record.id}"
        )
    except Exception as db_err:
        db.rollback()
        logger.exception(f"DB error: {db_err}")

    # 6) Return result
    return {
        "vm_name": vm_name,
        "vm_uuid": vm_uuid,
        "vm_ip": vm_ip,
        "selected_host": best.name,
        "selected_host_ip": best.ip,
        "state": "created",
        "resources": {
            "vcpus": vcpus,
            "ram": ram,
            "disk": disk_gib,
        },
        "script_output": output,
    }


# ------------------ Migration ------------------

def migrate_vm(db) -> Optional[Dict[str, Any]]:
    """
    Migration logic: detect overloaded host, migrate least memory VM.
    """
    hosts = db.query(models.Host).all()
    if len(hosts) < 2:
        logger.info("Migration skipped: Need at least 2 hosts")
        return None

    # Find overloaded host
    overloaded_host = None
    underloaded_host = None

    scores = {}
    for host in hosts:
        if not host.metrics:
            continue
        latest = sorted(host.metrics, key=lambda m: m.ts)[-1]
        score = calculate_host_score(latest)["score"]
        scores[host.id] = (host, score)

    sorted_hosts = sorted(scores.values(), key=lambda x: x[1])

    underloaded_host = sorted_hosts[0][0]
    overloaded_host = sorted_hosts[-1][0]

    if scores[overloaded_host.id][1] - scores[underloaded_host.id][1] < 0.15:
        logger.info("No migration needed (score difference < 0.15)")
        return None

    # Pick smallest VM on overloaded host
    vm = (
        db.query(models.VM)
        .filter(models.VM.host_id == overloaded_host.id)
        .order_by(models.VM.memory_mb.asc())
        .first()
    )

    if not vm:
        logger.info("No VM found to migrate")
        return None

    cmd = f"xe vm-migrate vm={vm.uuid} host={underloaded_host.uuid_xen} live=true"
    subprocess.run(shlex.split(cmd), check=True)

    vm.host_id = underloaded_host.id
    db.commit()

    return {
        "vm_uuid": vm.uuid,
        "source_host": overloaded_host.name,
        "target_host": underloaded_host.name
    }


def auto_migrate() -> Dict[str, Any]:
    """
    Helper used by Celery tasks.
    """
    db = SessionLocal()
    try:
        result = migrate_vm(db)
        if result:
            logger.info(f"[MIGRATION] Success {result}")
            return {"status": "migrated", "result": result}
        else:
            logger.info("[MIGRATION] No migration required")
            return {"status": "checked", "result": result}
    except Exception as e:
        logger.exception(f"[MIGRATION] Migration failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


# Manual testing
if __name__ == "__main__":
    db = SessionLocal()
    try:
        print("== manual scheduler test ==")
        best = select_least_loaded_host(db)
        print("Selected host:", best.name)
    finally:
        db.close()
