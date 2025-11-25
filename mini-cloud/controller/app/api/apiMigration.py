from fastapi import APIRouter, HTTPException
from app.db import SessionLocal
from app.scheduler import migrate_vm

router = APIRouter(prefix="/migration", tags=["Migration"])


@router.post("/manual")
def manual_migration():
    db = SessionLocal()
    try:
        result = migrate_vm(db)
        return {"status": "success", "result": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        db.close()
