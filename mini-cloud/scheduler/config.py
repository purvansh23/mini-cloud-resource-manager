# scheduler/config.py
import os

# Controller connection (set via env in docker-compose or systemd)
CONTROLLER_BASE_URL = os.getenv("CONTROLLER_BASE_URL", "http://controller:8000")
CONTROLLER_TOKEN = os.getenv("CONTROLLER_TOKEN", "CHANGE_ME")

# Scheduler behavior
REBALANCE_INTERVAL = int(os.getenv("REBALANCE_INTERVAL", "30"))  # seconds
HIGH_CPU_THRESHOLD = float(os.getenv("HIGH_CPU_THRESHOLD", "80.0"))  # percent
LOW_CPU_THRESHOLD = float(os.getenv("LOW_CPU_THRESHOLD", "60.0"))  # percent
HIGH_MEM_THRESHOLD = float(os.getenv("HIGH_MEM_THRESHOLD", "85.0"))
LOW_MEM_THRESHOLD = float(os.getenv("LOW_MEM_THRESHOLD", "70.0"))
EMERGENCY_CPU = float(os.getenv("EMERGENCY_CPU", "95.0"))

# Safety
MAX_CONCURRENT_MIGRATIONS = int(os.getenv("MAX_CONCURRENT_MIGRATIONS", "2"))
MAX_EMERGENCY_MIGRATIONS_PER_HOST = int(os.getenv("MAX_EMERGENCY_MIGRATIONS_PER_HOST", "1"))
MIGRATION_COOLDOWN = int(os.getenv("MIGRATION_COOLDOWN", "600"))  # seconds per-VM
HOST_COOLDOWN = int(os.getenv("HOST_COOLDOWN", "300"))  # seconds per-host

# Weights for host scoring
W_CPU = float(os.getenv("W_CPU", "0.6"))
W_MEM = float(os.getenv("W_MEM", "0.3"))
W_LOAD = float(os.getenv("W_LOAD", "0.1"))

# Logging / debug
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
