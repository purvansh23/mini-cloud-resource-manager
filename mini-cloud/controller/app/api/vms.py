# controller/app/api/vms.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app import db
from app.models import VM as VMModel  # SQLAlchemy model
from datetime import datetime
import uuid as _uuid
import logging

logger = logging.getLogger("controller.api.vms")
router = APIRouter(prefix="/vms", tags=["vms"])


class VMRegister(BaseModel):
    vm_uuid: Optional[str] = None       # XEN/XCP-NG UUID (preferred)
    host_id: Optional[str] = None      # host UUID where VM currently resides
    name: Optional[str] = None
    vcpus: Optional[int] = None
    memory_mb: Optional[int] = None
    state: Optional[str] = None


# --- helpers to cope with different model field names ---
def find_model_attr(model_cls, candidates):
    """
    Return the first attribute name from 'candidates' that the model class exposes,
    or None if none found.
    Works with SQLAlchemy InstrumentedAttributes on the class.
    """
    for cand in candidates:
        if hasattr(model_cls, cand):
            return cand
    return None


# candidate attribute names (common variants)
VM_UUID_CANDIDATES = ["vm_uuid", "xen_uuid", "uuid", "xen_id", "xen_uuid_string", "xenUuid"]
HOST_ID_CANDIDATES = ["host_id", "host_uuid", "host", "hostid"]
NAME_CANDIDATES = ["name", "name_label", "vm_name"]
VCPUS_CANDIDATES = ["vcpus", "vcpu", "cpu_count"]
MEM_CANDIDATES = ["memory_mb", "memory", "mem_mb", "memory_mb"]
STATE_CANDIDATES = ["state", "power_state"]


def _attr_name_from_discovered(field):
    """
    Normalize a discovered attribute into a string attribute name suitable for getattr.
    Accepts:
      - string names -> returned unchanged
      - SQLAlchemy InstrumentedAttribute -> return .key or .name if present
      - SQLAlchemy Column objects -> return .name if present
      - None -> return None
    """
    if not field:
        return None
    # already a string name
    if isinstance(field, str):
        return field
    # SQLAlchemy InstrumentedAttribute usually has .key
    if hasattr(field, "key"):
        return getattr(field, "key")
    # SQLAlchemy Column might have .name
    if hasattr(field, "name"):
        return getattr(field, "name")
    # fallback to string conversion (last resort)
    try:
        return str(field)
    except Exception:
        return None


def vm_row_to_scheduler_shape(vm_row: VMModel) -> Dict[str, Any]:
    """
    Convert SQLAlchemy VM model into the shape the scheduler expects.
    Best-effort mapping using discovered attributes, robust to InstrumentedAttribute.
    """
    try:
        cls = vm_row.__class__
        # discover attribute names (may return string or InstrumentedAttribute)
        vm_uuid_field = find_model_attr(cls, VM_UUID_CANDIDATES) or "vm_uuid"
        host_id_field = find_model_attr(cls, HOST_ID_CANDIDATES) or "host_id"
        name_field = find_model_attr(cls, NAME_CANDIDATES) or "name"
        vcpus_field = find_model_attr(cls, VCPUS_CANDIDATES) or "vcpus"
        mem_field = find_model_attr(cls, MEM_CANDIDATES) or "memory_mb"
        cpu_field = find_model_attr(cls, ["cpu_percent", "cpu"])  # optional

        # normalize into attribute names
        vm_uuid_attr = _attr_name_from_discovered(vm_uuid_field)
        host_id_attr = _attr_name_from_discovered(host_id_field)
        name_attr = _attr_name_from_discovered(name_field)
        vcpus_attr = _attr_name_from_discovered(vcpus_field)
        mem_attr = _attr_name_from_discovered(mem_field)
        cpu_attr = _attr_name_from_discovered(cpu_field)

        vm_uuid = getattr(vm_row, vm_uuid_attr, None) if vm_uuid_attr else None
        host_id = getattr(vm_row, host_id_attr, None) if host_id_attr else None
        name = getattr(vm_row, name_attr, None) if name_attr else None
        vcpus = getattr(vm_row, vcpus_attr, None) if vcpus_attr else 1
        mem_mb = getattr(vm_row, mem_attr, None) if mem_attr else 0

        # safe numeric parsing
        try:
            cpu_percent = float(getattr(vm_row, cpu_attr, 0.0) or 0.0) if cpu_attr else 0.0
        except Exception:
            cpu_percent = 0.0

        return {
            "vm_id": str(getattr(vm_row, "id", vm_uuid or "")),
            "vm_uuid": str(vm_uuid) if vm_uuid is not None else "",
            "name": name,
            "host_id": host_id,
            "vcpus": vcpus or 1,
            "mem_bytes": int(mem_mb or 0) * 1024 * 1024,
            "cpu_percent": cpu_percent,
            "protected": bool(getattr(vm_row, "protected", False)),
            "last_migrated_at": getattr(vm_row, "last_migrated_at", None),
        }
    except Exception:
        logger.exception("vm_row_to_scheduler_shape failed for row: %r", vm_row)
        # very defensive fallback
        return {
            "vm_id": str(getattr(vm_row, "id", "")),
            "vm_uuid": str(getattr(vm_row, "vm_uuid", "")),
            "name": getattr(vm_row, "name", None),
            "host_id": getattr(vm_row, "host_id", None),
            "vcpus": getattr(vm_row, "vcpus", 1),
            "mem_bytes": 0,
            "cpu_percent": 0.0,
            "protected": False,
            "last_migrated_at": None,
        }


@router.post("/register", status_code=200)
def register_vm(payload: VMRegister):
    """
    Upsert a VM row in the controller DB. This handler is defensive: it will try
    common model attribute names and (if necessary) create a new record using the best guessed columns.
    """
    session = db.SessionLocal()
    try:
        # discover which field on VMModel stores xen UUID
        vm_uuid_field = find_model_attr(VMModel, VM_UUID_CANDIDATES)
        host_id_field = find_model_attr(VMModel, HOST_ID_CANDIDATES)
        name_field = find_model_attr(VMModel, NAME_CANDIDATES)
        vcpus_field = find_model_attr(VMModel, VCPUS_CANDIDATES)
        mem_field = find_model_attr(VMModel, MEM_CANDIDATES)
        state_field = find_model_attr(VMModel, STATE_CANDIDATES)

        if vm_uuid_field is None:
            # Can't find any reasonable UUID field on the model; return clear error
            msg = (
                "Controller VM model does not expose a VM UUID attribute. "
                "Checked candidates: " + ", ".join(VM_UUID_CANDIDATES)
            )
            logger.error(msg)
            raise HTTPException(status_code=500, detail=msg)

        # try to find existing row by xen UUID (use discovered field)
        query = {vm_uuid_field: payload.vm_uuid} if payload.vm_uuid else {}
        vm = None
        if payload.vm_uuid:
            vm = session.query(VMModel).filter(getattr(VMModel, vm_uuid_field) == payload.vm_uuid).first()
        else:
            # if caller didn't pass vm_uuid, try to find by name+host as fallback (best-effort)
            if payload.name and host_id_field and payload.host_id:
                vm = (
                    session.query(VMModel)
                    .filter(getattr(VMModel, name_field) == payload.name, getattr(VMModel, host_id_field) == payload.host_id)
                    .first()
                )

        now = datetime.utcnow()

        if vm:
            # update fields if present on model
            if name_field and payload.name:
                setattr(vm, name_field, payload.name)
            if host_id_field and payload.host_id is not None:
                setattr(vm, host_id_field, payload.host_id)
            if vcpus_field and payload.vcpus is not None:
                setattr(vm, vcpus_field, payload.vcpus)
            if mem_field and payload.memory_mb is not None:
                setattr(vm, mem_field, payload.memory_mb)
            if state_field and payload.state is not None:
                setattr(vm, state_field, payload.state)
            # optional timestamps
            if hasattr(vm, "last_seen"):
                try:
                    setattr(vm, "last_seen", now)
                except Exception:
                    pass
            session.add(vm)
            session.commit()
            return {"status": "updated", "vm_id": getattr(vm, "id", None), "vm_uuid": getattr(vm, vm_uuid_field, None)}
        else:
            # create new row: build kwargs depending on model attribute names present
            create_kwargs = {}
            # id
            create_kwargs["id"] = str(_uuid.uuid4())
            # xen uuid
            create_kwargs[vm_uuid_field] = payload.vm_uuid or None
            # name
            if name_field:
                create_kwargs[name_field] = payload.name or (payload.vm_uuid or "")
            # host id
            if host_id_field:
                create_kwargs[host_id_field] = payload.host_id
            # vcpus / memory
            if vcpus_field:
                create_kwargs[vcpus_field] = payload.vcpus or 1
            if mem_field:
                create_kwargs[mem_field] = payload.memory_mb or 0
            if state_field:
                create_kwargs[state_field] = payload.state or "unknown"

            new_vm = VMModel(**create_kwargs)
            # set created_at if model has attribute
            if hasattr(new_vm, "created_at"):
                try:
                    setattr(new_vm, "created_at", now)
                except Exception:
                    pass
            session.add(new_vm)
            session.commit()
            return {"status": "created", "vm_id": getattr(new_vm, "id", None), "vm_uuid": getattr(new_vm, vm_uuid_field, None)}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.exception("register_vm failed payload=%r", payload.dict())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/", response_model=List[Dict[str, Any]])
def list_vms():
    """
    Return list of VMs in the shape the scheduler expects.
    """
    session = db.SessionLocal()
    try:
        rows = session.query(VMModel).all()
        result = [vm_row_to_scheduler_shape(r) for r in rows]
        return result
    except Exception:
        logger.exception("Failed to list VMs")
        return []
    finally:
        session.close()
