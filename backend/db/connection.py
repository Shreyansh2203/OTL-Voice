
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Project root (…/OTL), so the default path is stable no matter where uvicorn
# was started from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "otl_dummy.db"


def db_path() -> Path:
    configured = os.getenv("OTL_DB_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else _DEFAULT_DB


#: Convenience for scripts and log messages; call :func:`db_path` when the env
#: may have changed since import.
DB_PATH = db_path()


@contextmanager
def get_conn(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn(write=True) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def is_seeded() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()
    return bool(row and row["n"])
