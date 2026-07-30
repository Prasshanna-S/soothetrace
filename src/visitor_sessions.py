"""Anonymous, isolated, short-lived browser sessions for the hosted demo."""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:
    from . import database, store
except ImportError:
    import database
    import store


TOKEN_BYTES = 32
DEFAULT_TTL_SECONDS = 60 * 60
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VisitorSession:
    token: str
    token_hash: str
    created_at: str
    expires_at: str
    consented: bool
    database_path: Path
    audio_root: Path
    is_new: bool = False

    def public(self, retention_seconds: int) -> dict:
        return {
            "status": "ready",
            "consented": self.consented,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retention_seconds": retention_seconds,
        }


class VisitorSessionManager:
    """Own the central token registry and one cloned demo database per visitor."""

    def __init__(
        self,
        *,
        template_db: str | Path,
        registry_db: str | Path,
        visitor_root: str | Path,
        audio_root: str | Path,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: Callable[[], datetime] = _utc_now,
    ):
        self.template_db = Path(template_db).expanduser().resolve()
        self.registry_db = Path(registry_db).expanduser().resolve()
        self.visitor_root = Path(visitor_root).expanduser().resolve()
        self.audio_base = Path(audio_root).expanduser().resolve()
        self.ttl_seconds = max(60, int(ttl_seconds))
        self._now = now
        self.visitor_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.audio_base / "visitors").mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        self._init_registry()

    def _init_registry(self) -> None:
        connection = database.connect(str(self.registry_db))
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS visitor_session ("
                "token_hash TEXT PRIMARY KEY,"
                "created_at TEXT NOT NULL,"
                "expires_at TEXT NOT NULL,"
                "last_seen_at TEXT NOT NULL,"
                "consented_at TEXT"
                ")"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_visitor_expiry "
                "ON visitor_session(expires_at)"
            )
            connection.commit()
        finally:
            connection.close()

    def _paths(self, token_hash: str) -> tuple[Path, Path]:
        if not _HASH_PATTERN.fullmatch(token_hash):
            raise ValueError("invalid visitor session hash")
        database_path = self.visitor_root / token_hash / "episodes.db"
        audio_root = self.audio_base / "visitors" / token_hash
        return database_path, audio_root

    def _clone_template(self, destination: Path) -> None:
        store.init_db(str(self.template_db))
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source = database.connect(str(self.template_db))
        target = database.connect(str(destination))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()

    def _row(self, token_hash: str):
        connection = database.connect(str(self.registry_db))
        try:
            return connection.execute(
                "SELECT * FROM visitor_session WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        finally:
            connection.close()

    def _render(
        self,
        token: str,
        row,
        *,
        is_new: bool = False,
    ) -> VisitorSession:
        database_path, audio_root = self._paths(row["token_hash"])
        return VisitorSession(
            token=token,
            token_hash=row["token_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            consented=bool(row["consented_at"]),
            database_path=database_path,
            audio_root=audio_root,
            is_new=is_new,
        )

    def _new(self) -> VisitorSession:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        token_hash = _digest(token)
        created = self._now().astimezone(timezone.utc)
        expires = created + timedelta(seconds=self.ttl_seconds)
        database_path, audio_root = self._paths(token_hash)
        self._clone_template(database_path)
        audio_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = database.connect(str(self.registry_db))
        try:
            connection.execute(
                "INSERT INTO visitor_session("
                "token_hash,created_at,expires_at,last_seen_at,consented_at"
                ") VALUES(?,?,?,?,NULL)",
                (
                    token_hash,
                    created.isoformat(),
                    expires.isoformat(),
                    created.isoformat(),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM visitor_session WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        except Exception:
            self._delete_paths(token_hash)
            raise
        finally:
            connection.close()
        return self._render(token, row, is_new=True)

    def resolve(self, token: str | None = None) -> VisitorSession:
        if not isinstance(token, str) or len(token) < 20 or len(token) > 200:
            return self._new()
        token_hash = _digest(token)
        row = self._row(token_hash)
        if row is None:
            return self._new()
        expires = _as_datetime(row["expires_at"])
        if expires is None or expires <= self._now().astimezone(timezone.utc):
            self._delete_hash(token_hash)
            return self._new()
        database_path, audio_root = self._paths(token_hash)
        if not database_path.is_file():
            self._delete_hash(token_hash)
            return self._new()
        audio_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = database.connect(str(self.registry_db))
        try:
            connection.execute(
                "UPDATE visitor_session SET last_seen_at=? WHERE token_hash=?",
                (self._now().astimezone(timezone.utc).isoformat(), token_hash),
            )
            connection.commit()
        finally:
            connection.close()
        return self._render(token, row)

    def consent(self, token: str) -> VisitorSession | None:
        if not isinstance(token, str) or len(token) < 20 or len(token) > 200:
            return None
        token_hash = _digest(token)
        row = self._row(token_hash)
        if row is None:
            return None
        expires = _as_datetime(row["expires_at"])
        if expires is None or expires <= self._now().astimezone(timezone.utc):
            self._delete_hash(token_hash)
            return None
        now = self._now().astimezone(timezone.utc).isoformat()
        connection = database.connect(str(self.registry_db))
        try:
            connection.execute(
                "UPDATE visitor_session "
                "SET consented_at=COALESCE(consented_at,?),last_seen_at=? "
                "WHERE token_hash=?",
                (now, now, token_hash),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM visitor_session WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
        finally:
            connection.close()
        return self._render(token, updated)

    def _delete_paths(self, token_hash: str) -> None:
        database_path, audio_root = self._paths(token_hash)
        database_directory = database_path.parent.resolve()
        audio_directory = audio_root.resolve()
        if database_directory.parent == self.visitor_root:
            shutil.rmtree(database_directory, ignore_errors=True)
        expected_audio_parent = (self.audio_base / "visitors").resolve()
        if audio_directory.parent == expected_audio_parent:
            shutil.rmtree(audio_directory, ignore_errors=True)

    def _delete_hash(self, token_hash: str) -> bool:
        if not _HASH_PATTERN.fullmatch(token_hash):
            return False
        connection = database.connect(str(self.registry_db))
        try:
            removed = connection.execute(
                "DELETE FROM visitor_session WHERE token_hash=?",
                (token_hash,),
            ).rowcount
            connection.commit()
        finally:
            connection.close()
        if removed:
            self._delete_paths(token_hash)
        return bool(removed)

    def delete(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) < 20 or len(token) > 200:
            return False
        return self._delete_hash(_digest(token))

    def cleanup_expired(self) -> int:
        now = self._now().astimezone(timezone.utc).isoformat()
        connection = database.connect(str(self.registry_db))
        try:
            hashes = [
                row["token_hash"]
                for row in connection.execute(
                    "SELECT token_hash FROM visitor_session WHERE expires_at<=?",
                    (now,),
                ).fetchall()
            ]
        finally:
            connection.close()
        return sum(1 for token_hash in hashes if self._delete_hash(token_hash))
