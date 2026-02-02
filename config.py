from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def load_env() -> None:
    candidates = [
        BASE_DIR / ".env",
        BASE_DIR / "venv" / ".env",
    ]
    for path in candidates:
        if path.exists():
            load_dotenv(path)
            return


load_env()


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value
