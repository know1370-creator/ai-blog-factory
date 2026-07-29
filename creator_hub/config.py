"""Central configuration for the V9 modular migration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'creator.db'}")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-1")
    APP_VERSION = "14.0"
