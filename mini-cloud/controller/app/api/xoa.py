# app/api/xoa.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from app.xoa_client import get_xoa_rest_client

router = APIRouter(prefix="/xoa", tags=["xoa"])

class CreateVMPayload(BaseModel):
    pool_uuid: str = Field(..., description="Pool UUID to create VM under")
    name_label: str = Field(..., description="name_label for new VM")
    template_uuid: Optional[str] = None
    boot: bool = False
    sync: bool = False

@router.get("/pools")
def list_pools():
    client = get_xoa_rest_client()
    try:
        return {"pools": client.list_pools()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates/{pool_uuid}")
def list_templates(pool_uuid: str):
    client = get_xoa_rest_client()
    try:
        return {"templates": client.list_templates_in_pool(pool_uuid)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create_vm")
def create_vm(payload: CreateVMPayload):
    client = get_xoa_rest_client()
    try:
        body = {
            "name_label": payload.name_label,
            "template": payload.template_uuid,
            "boot": payload.boot
        }
        res = client.create_vm_on_pool(payload.pool_uuid, body, sync=payload.sync)
        return {"result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
