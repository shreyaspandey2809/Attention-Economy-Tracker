from fastapi.testclient import TestClient

from attention_tracker.synthetic.archetypes import ARCHETYPES
from mock_backend.main import app

client = TestClient(app)


def test_list_archetypes_matches_registered_archetypes():
    response = client.get("/archetypes")

    assert response.status_code == 200
    assert response.json() == sorted(ARCHETYPES.keys())


def test_simulate_day_rejects_unknown_archetype():
    response = client.post("/simulate-day", json={"archetype": "NOT_A_REAL_ARCHETYPE"})

    assert response.status_code == 400


def test_simulate_day_succeeds_for_every_registered_archetype():
    for archetype in ARCHETYPES:
        response = client.post(
            "/simulate-day", json={"archetype": archetype, "user_id": "pytest_user"}
        )

        assert response.status_code == 200, (
            f"{archetype} failed with body: {response.text}"
        )

        body = response.json()
        assert body["archetype"] == archetype
        assert body["user_id"] == "pytest_user"
        assert isinstance(body["scoring_status"], str) and body["scoring_status"]
        assert isinstance(body["scoring_message"], str) and body["scoring_message"]
        assert isinstance(body["per_app_features"], list)


def test_simulate_day_per_app_features_are_sorted_by_heuristic_score_desc():
    response = client.post("/simulate-day", json={"archetype": "DOOMSCROLLER"})
    body = response.json()

    scores = [app["heuristic_score"] for app in body["per_app_features"]]
    assert scores == sorted(scores, reverse=True)


def test_simulate_day_default_user_id():
    response = client.post("/simulate-day", json={"archetype": "BALANCED"})

    assert response.json()["user_id"] == "demo_user"


def test_simulate_day_exposes_rejected_pairs_and_overlap_counts():
    response = client.post("/simulate-day", json={"archetype": "DOOMSCROLLER"})
    body = response.json()

    assert isinstance(body["rejected_pairs_count"], int)
    assert isinstance(body["overlapping_sessions_count"], int)
    assert body["rejected_pairs_count"] == 0
    assert body["overlapping_sessions_count"] == 0