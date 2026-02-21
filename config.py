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


def _normalize_env_value(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = _normalize_env_value(os.getenv(name, default))
    if required and not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value
