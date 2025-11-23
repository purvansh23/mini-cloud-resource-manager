import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

if not ENV_PATH.exists():
    print(f"WARNING: .env not found at {ENV_PATH}")

# Try imports compatible with both pydantic v1 and v2
try:
    # pydantic v1
    from pydantic import BaseSettings, Field
    PydanticVersion = 1
except Exception:
    try:
        # pydantic v2: BaseSettings moved to pydantic-settings
        from pydantic_settings import BaseSettings
        from pydantic import Field  # Field still in pydantic
        PydanticVersion = 2
    except Exception as e:
        raise ImportError(
            "Could not import BaseSettings from pydantic or pydantic_settings. "
            "If you have pydantic v2, run: pip install pydantic-settings"
        ) from e

# Define settings fields
class Settings(BaseSettings):
    # database
    db_host: str = Field(..., env="DB_HOST")
    db_port: int = Field(5432, env="DB_PORT")
    db_name: str = Field(..., env="DB_NAME")
    db_user: str = Field(..., env="DB_USER")
    db_pass: str = Field(..., env="DB_PASS")
    # broker / extras
    redis_url: str = Field(..., env="REDIS_URL")
    # XOA
    xoa_base_url: str = Field(..., env="XOA_BASE_URL")
    xoa_token: str = Field(..., env="XOA_TOKEN")

    # pydantic v1 style
    class Config:
        env_file = str(ENV_PATH)
        env_file_encoding = "utf-8"
        extra = "ignore"   # ignore unknown fields like APP_ENV

# pydantic v2 requires model_config to be set; ensure it's configured too
# this code will not break for v1
try:
    # merge into existing model_config if present
    existing = getattr(Settings, "model_config", {}) or {}
    merged = dict(existing)
    merged.update({
        "env_file": str(ENV_PATH),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    })
    Settings.model_config = merged
except Exception:
    # if pydantic v1, model_config won't exist — ignore
    pass

# single settings instance imported elsewhere
settings = Settings()