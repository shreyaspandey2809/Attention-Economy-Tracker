import pytest

from attention_tracker.api.admin import main
from attention_tracker.storage.db import Database
from attention_tracker.storage.repository import Repository


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "t.db")


def test_create_device_prints_a_working_token_once(db_path, capsys):
    assert main(["--db", db_path, "create-device", "u1"]) == 0
    out = capsys.readouterr().out
    token = next(line.split()[-1] for line in out.splitlines() if line.startswith("token:"))

    from fastapi.testclient import TestClient

    from attention_tracker.api.app import create_app

    client = TestClient(create_app(db_path=db_path, model_dir=db_path + ".nomodels"))
    assert client.get("/v1/models", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_same_user_can_get_several_devices(db_path, capsys):
    main(["--db", db_path, "create-device", "u1"])
    main(["--db", db_path, "create-device", "u1"])
    n = Database(db_path).conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
    assert n == 2


def test_revoke_device(db_path, capsys):
    main(["--db", db_path, "create-device", "u1"])
    device_id = next(l.split()[-1] for l in capsys.readouterr().out.splitlines() if l.startswith("device_id:"))
    assert main(["--db", db_path, "revoke-device", device_id]) == 0
    assert main(["--db", db_path, "revoke-device", device_id]) == 1


def test_delete_user_requires_yes(db_path):
    main(["--db", db_path, "create-device", "u1"])
    assert main(["--db", db_path, "delete-user", "u1"]) == 2
    assert Repository(Database(db_path)).get_user("u1") is not None
    assert main(["--db", db_path, "delete-user", "u1", "--yes"]) == 0
    assert Repository(Database(db_path)).get_user("u1") is None
    assert main(["--db", db_path, "delete-user", "u1", "--yes"]) == 1


def test_score_and_list_users(db_path, capsys, make_events, monkeypatch, tmp_path):
    monkeypatch.setenv("ATTENTION_MODEL_DIR", str(tmp_path / "no_models"))
    main(["--db", db_path, "create-device", "u1"])
    repo = Repository(Database(db_path))
    repo.insert_events("u1", make_events("u1"))
    capsys.readouterr()

    main(["--db", db_path, "list-users"])
    assert "u1\tconsent=no\tstale=True" in capsys.readouterr().out

    assert main(["--db", db_path, "score"]) == 0
    assert "u1:" in capsys.readouterr().out
    main(["--db", db_path, "list-users"])
    assert "stale=False" in capsys.readouterr().out
    assert main(["--db", db_path, "score", "--user", "ghost"]) == 1
