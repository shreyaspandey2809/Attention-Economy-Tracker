"""SQLite connection + plain-SQL migrations.

Migrations are the `NNN_name.sql` files in `migrations/`, applied in order and
recorded in `schema_migrations`. There is no ORM: the SQL stays visible.

One shared connection guarded by a re-entrant lock is enough for a pilot-scale
service; FastAPI runs sync endpoints in a thread pool, so the lock serialises
writers instead of relying on SQLite's own locking.
"""

import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


class Database:
    def __init__(self, path: str | Path = ":memory:", migrations_dir: Path | None = None):
        self.path = str(path)
        self._migrations_dir = migrations_dir or MIGRATIONS_DIR
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        migrate(self.conn, self._migrations_dir)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialised BEGIN..COMMIT block; rolls back on any exception."""
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def _migration_files(directory: Path) -> list[tuple[int, Path]]:
    found = []
    for p in sorted(directory.glob("*.sql")):
        m = _MIGRATION_RE.match(p.name)
        if m is None:
            raise ValueError(f"bad migration file name: {p.name} (expected NNN_name.sql)")
        found.append((int(m.group(1)), p))
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"migrations must be numbered 001..N with no gaps, got {versions}")
    return found


def latest_schema_version(migrations_dir: Path | None = None) -> int:
    return len(_migration_files(migrations_dir or MIGRATIONS_DIR))


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [r["version"] for r in rows]


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[int]:
    """Apply any unapplied migrations. Returns the versions applied now."""
    files = _migration_files(migrations_dir or MIGRATIONS_DIR)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    done = set(applied_versions(conn))
    applied = []
    for version, path in files:
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        # executescript() commits any open transaction first, so wrap explicitly.
        conn.executescript(
            f"BEGIN;\n{script}\nINSERT INTO schema_migrations(version) VALUES ({version});\nCOMMIT;"
        )
        applied.append(version)
    return applied
