"""Shared SQLite connection settings for every SootheTrace domain."""

from __future__ import annotations

import sqlite3
from pathlib import Path

try:
    from . import config
except ImportError:
    import config


BUSY_TIMEOUT_MS = 10_000


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open one row-based connection with the release-safe SQLite pragmas."""
    database_path = path or config.DB_PATH
    if database_path != ":memory:":
        Path(database_path).expanduser().resolve().parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    connection = sqlite3.connect(
        database_path,
        timeout=BUSY_TIMEOUT_MS / 1000,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    if database_path != ":memory:":
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
    return connection
