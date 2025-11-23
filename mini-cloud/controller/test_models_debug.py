# test_models_debug.py
# Safe import: clear Base.metadata, remove cached module, then import models and create tables.
import sys
import importlib
from app.db import Base, engine
from sqlalchemy import text

print("cwd:", sys.path[0])

# Clear any previously-registered Table objects on Base.metadata (prevents duplicate definition errors)
try:
    Base.metadata.clear()
    print("Cleared Base.metadata.")
except Exception as e:
    print("Warning clearing Base.metadata:", e)

# Remove cached app.models if present so import is fresh
if "app.models" in sys.modules:
    del sys.modules["app.models"]
    print("Removed cached app.models from sys.modules.")

# Import models (this will register tables on Base.metadata)
import app.models
importlib.reload(app.models)
print("Imported app.models from:", app.models.__file__)

# Show classes found in app.models
attrs = [name for name in dir(app.models) if not name.startswith('_')]
print("app.models public attrs sample:", attrs[:60])

# Show metadata table keys that SQLAlchemy knows about
print("Base.metadata.tables keys:", list(Base.metadata.tables.keys()))

# Create tables in DB
print("Calling Base.metadata.create_all(bind=engine)...")
Base.metadata.create_all(bind=engine)
print("create_all() complete.")

# Query DB to list tables
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type='BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema, table_name;
    """)).fetchall()
    if not rows:
        print("No tables found for this connection after create_all().")
    else:
        print("Tables visible via SQL:")
        for s, t in rows:
            print(f"  {s}.{t}")

print("DONE ✅")
