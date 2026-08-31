from __future__ import annotations

import os


def is_dev_mode() -> bool:
    return os.getenv("DEV_MODE", "false").strip().lower() == "true"


def is_test_mode() -> bool:
    return os.getenv("TEST_MODE", "false").strip().lower() == "true"


def cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:4173,http://localhost:8000,http://localhost,http://127.0.0.1:5173,http://127.0.0.1:4173,http://127.0.0.1:8000",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]
