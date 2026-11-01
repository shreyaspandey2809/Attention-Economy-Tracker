import pytest

from tests.api.conftest import payload


def _onboard(client, issue, user_id="u1"):
    headers = issue(user_id)
    assert client.post("/v1/consent", headers=headers).status_code == 200
    return headers


# ---- health / auth ---------------------------------------------------------


def test_health_is_public(client):
    body = client.get("/v1/health").json()
    assert body["status"] == "ok" and body["schema_version"] >= 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/consent"),
        ("post", "/v1/events"),
        ("get", "/v1/users/u1/scores"),
        ("post", "/v1/labels/sas-sv"),
        ("get", "/v1/models"),
        ("get", "/v1/users/u1/export"),
        ("delete", "/v1/users/u1"),
    ],
)
def test_every_endpoint_but_health_requires_a_token(client, issue, method, path):
    issue("u1")
    assert getattr(client, method)(path).status_code == 401
    r = getattr(client, method)(path, headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_revoked_device_is_rejected(client, issue):
    headers = issue("u1")
    assert client.get("/v1/models", headers=headers).status_code == 200
    device_id = client.app.state.db.conn.execute("SELECT device_id FROM devices").fetchone()["device_id"]
    client.app.state.repo.revoke_device(device_id)
    assert client.get("/v1/models", headers=headers).status_code == 401


def test_token_is_stored_hashed_only(client, issue):
    headers = issue("u1")
    token = headers["Authorization"].split()[1]
    stored = client.app.state.db.conn.execute("SELECT token_hash FROM devices").fetchone()["token_hash"]
    assert stored != token and len(stored) == 64


# ---- consent + ingest -------------------------------------------------------


def test_events_refused_until_consent_is_recorded(client, issue, make_events):
    headers = issue("u1")
    r = client.post("/v1/events", json=payload(make_events("u1")), headers=headers)
    assert r.status_code == 403 and "consent" in r.json()["detail"]

    client.post("/v1/consent", headers=headers)
    assert client.post("/v1/events", json=payload(make_events("u1")), headers=headers).status_code == 200


def test_ingest_is_idempotent(client, issue, make_events):
    headers = _onboard(client, issue)
    events = make_events("u1")

    first = client.post("/v1/events", json=payload(events), headers=headers).json()
    assert first == {"accepted": len(events), "duplicates": 0}
    second = client.post("/v1/events", json=payload(events), headers=headers).json()
    assert second == {"accepted": 0, "duplicates": len(events)}


def test_events_for_another_user_are_refused_and_nothing_is_stored(client, issue, make_events):
    headers = _onboard(client, issue)
    mixed = make_events("u1")[:3] + make_events("someone_else")[:3]
    r = client.post("/v1/events", json=payload(mixed), headers=headers)
    assert r.status_code == 403
    assert client.app.state.repo.load_events("u1") == []


def test_invalid_event_rejects_the_whole_batch(client, issue, make_events):
    headers = _onboard(client, issue)
    body = payload(make_events("u1")[:3])
    body["events"][0]["timestamp"] = "2026-03-02T10:00:00"  # naive -> RawEvent rejects
    assert client.post("/v1/events", json=body, headers=headers).status_code == 422
    assert client.app.state.repo.load_events("u1") == []


def test_oversized_batch_is_rejected(client, issue, make_events):
    headers = _onboard(client, issue)
    one = payload(make_events("u1")[:1])["events"][0]
    r = client.post("/v1/events", json={"events": [one] * 5001}, headers=headers)
    assert r.status_code == 422


# ---- scores ----------------------------------------------------------------


def test_scores_are_computed_on_demand_and_cached(client, issue, make_events):
    headers = _onboard(client, issue)
    client.post("/v1/events", json=payload(make_events("u1")), headers=headers)

    body = client.get("/v1/users/u1/scores", headers=headers).json()
    assert body["scoring_status"] == "heuristic_only"
    assert len(body["daily"]) >= 2 and body["apps"]
    for d in body["daily"]:
        assert 0 <= d["heuristic_score"] <= 10 and 0 <= d["distraction_score"] <= 10
        assert d["addiction_model_score"] is None
    assert client.app.state.repo.get_user("u1")["scores_stale"] == 0


def test_new_events_trigger_rescoring_on_next_read(client, issue, make_events):
    headers = _onboard(client, issue)
    client.post("/v1/events", json=payload(make_events("u1", num_days=2)), headers=headers)
    days_before = len(client.get("/v1/users/u1/scores", headers=headers).json()["daily"])

    client.post("/v1/events", json=payload(make_events("u1", num_days=4)), headers=headers)
    days_after = len(client.get("/v1/users/u1/scores", headers=headers).json()["daily"])
    assert days_after > days_before


def test_scores_date_filter(client, issue, make_events):
    headers = _onboard(client, issue)
    client.post("/v1/events", json=payload(make_events("u1")), headers=headers)
    days = [d["day"] for d in client.get("/v1/users/u1/scores", headers=headers).json()["daily"]]

    only = client.get("/v1/users/u1/scores", params={"from": days[-1]}, headers=headers).json()
    assert [d["day"] for d in only["daily"]] == [days[-1]]
    assert {a["day"] for a in only["apps"]} == {days[-1]}


def test_scores_for_user_with_no_data_are_empty(client, issue):
    headers = _onboard(client, issue)
    body = client.get("/v1/users/u1/scores", headers=headers).json()
    assert body["daily"] == [] and body["apps"] == []


def test_user_cannot_read_anothers_scores_export_or_delete(client, issue):
    a, _b = issue("alice"), issue("bob")
    for method, path in (
        ("get", "/v1/users/bob/scores"),
        ("get", "/v1/users/bob/export"),
        ("delete", "/v1/users/bob"),
    ):
        assert getattr(client, method)(path, headers=a).status_code == 403


# ---- SAS-SV ----------------------------------------------------------------


@pytest.mark.parametrize("bad", [9, 61, 0, -5])
def test_sas_sv_total_out_of_range_is_rejected(client, issue, bad):
    headers = issue("u1")
    assert client.post("/v1/labels/sas-sv", json={"sas_sv_total": bad}, headers=headers).status_code == 422


def test_sas_sv_rejects_item_level_data(client, issue):
    headers = issue("u1")
    r = client.post("/v1/labels/sas-sv", json={"sas_sv_total": 30, "items": [1] * 10}, headers=headers)
    assert r.status_code == 422


def test_sas_sv_total_is_stored_for_the_token_user(client, issue):
    headers = issue("u1")
    r = client.post("/v1/labels/sas-sv", json={"sas_sv_total": 37}, headers=headers)
    assert r.status_code == 200 and r.json()["user_id"] == "u1"
    assert client.app.state.repo.get_sas_sv("u1")["sas_sv_total"] == 37


# ---- models ----------------------------------------------------------------


def test_models_endpoint_is_empty_without_a_registry(client, issue):
    headers = issue("u1")
    assert client.get("/v1/models", headers=headers).json() == {"models": []}


# ---- export / delete ---------------------------------------------------------


def test_export_then_delete_removes_everything_and_kills_the_token(client, issue, make_events):
    headers = _onboard(client, issue)
    events = make_events("u1")
    client.post("/v1/events", json=payload(events), headers=headers)
    client.get("/v1/users/u1/scores", headers=headers)
    client.post("/v1/labels/sas-sv", json={"sas_sv_total": 30}, headers=headers)

    dump = client.get("/v1/users/u1/export", headers=headers).json()
    assert len(dump["raw_events"]) == len(events)
    assert dump["scores"] and dump["daily_scores"] and dump["sas_sv_label"]
    assert "token_hash" not in repr(dump)

    assert client.delete("/v1/users/u1", headers=headers).status_code == 204
    conn = client.app.state.db.conn
    for table in ("users", "devices", "raw_events", "sessions", "feature_vectors", "scores", "daily_scores"):
        assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0, table
    assert client.get("/v1/users/u1/export", headers=headers).status_code == 401


def test_delete_leaves_other_users_data_alone(client, issue, make_events):
    a = _onboard(client, issue, "alice")
    b = _onboard(client, issue, "bob")
    client.post("/v1/events", json=payload(make_events("alice")), headers=a)
    client.post("/v1/events", json=payload(make_events("bob")), headers=b)

    client.delete("/v1/users/alice", headers=a)
    assert len(client.get("/v1/users/bob/export", headers=b).json()["raw_events"]) == len(make_events("bob"))
