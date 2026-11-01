import sqlite3

import pytest

from attention_tracker.storage.db import (
    Database,
    applied_versions,
    latest_schema_version,
    migrate,
)

EXPECTED_TABLES = {
    "users",
    "devices",
    "app_metadata",
    "raw_events",
    "sessions",
    "feature_vectors",
    "scores",
    "daily_scores",
    "sas_sv_labels",
    "schema_migrations",
}


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


def test_fresh_database_has_every_m8_table():
    db = Database(":memory:")
    assert EXPECTED_TABLES <= _tables(db.conn)


def test_migrations_are_recorded_and_idempotent():
    db = Database(":memory:")
    assert applied_versions(db.conn) == list(range(1, latest_schema_version() + 1))
    assert migrate(db.conn) == []


def test_foreign_keys_are_enforced():
    db = Database(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as c:
            c.execute(
                "INSERT INTO devices(device_id, user_id, token_hash, created_at) VALUES ('d', 'ghost', 'h', 't')"
            )


def test_transaction_rolls_back_on_error():
    db = Database(":memory:")
    with pytest.raises(RuntimeError):
        with db.transaction() as c:
            c.execute("INSERT INTO users(user_id, created_at) VALUES ('u1', 't')")
            raise RuntimeError("boom")
    assert db.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0


def test_sas_sv_total_must_be_in_range():
    db = Database(":memory:")
    with db.transaction() as c:
        c.execute("INSERT INTO users(user_id, created_at) VALUES ('u1', 't')")
    for bad in (9, 61):
        with pytest.raises(sqlite3.IntegrityError):
            with db.transaction() as c:
                c.execute(
                    "INSERT INTO sas_sv_labels(user_id, sas_sv_total, collected_at) VALUES ('u1', ?, 't')",
                    (bad,),
                )


def test_file_database_persists_across_connections(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path)
    with db.transaction() as c:
        c.execute("INSERT INTO users(user_id, created_at) VALUES ('u1', 't')")
    db.close()

    again = Database(path)
    assert again.conn.execute("SELECT user_id FROM users").fetchone()["user_id"] == "u1"
    assert applied_versions(again.conn) == list(range(1, latest_schema_version() + 1))


def test_migration_gap_is_rejected(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (tmp_path / "003_c.sql").write_text("CREATE TABLE c (x INTEGER);")
    with pytest.raises(ValueError, match="no gaps"):
        Database(":memory:", migrations_dir=tmp_path)


def test_bad_migration_name_is_rejected(tmp_path):
    (tmp_path / "init.sql").write_text("CREATE TABLE a (x INTEGER);")
    with pytest.raises(ValueError, match="bad migration file name"):
        Database(":memory:", migrations_dir=tmp_path)


def test_failed_migration_leaves_nothing_applied(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE b (x INTEGER); THIS IS NOT SQL;")
    with pytest.raises(sqlite3.Error):
        Database(":memory:", migrations_dir=tmp_path)
