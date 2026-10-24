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

def test_simulate_day_exposes_distraction_score_distinct_from_addiction():
    response = client.post("/simulate-day", json={"archetype": "COMPULSIVE_CHECKER"})
    apps = response.json()["per_app_features"]

    assert apps
    for a in apps:
        assert 0.0 <= a["distraction_score"] <= 10.0
    assert any(a["distraction_score"] != a["heuristic_score"] for a in apps)


def test_simulate_day_without_trained_models_is_heuristic_only(monkeypatch, tmp_path):
    import mock_backend.main as backend

    monkeypatch.setenv("ATTENTION_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(backend, "_models", {})

    body = client.post("/simulate-day", json={"archetype": "BALANCED"}).json()

    assert body["scoring_status"] == "heuristic_only"
    assert body["model_versions"] == {}
    for a in body["per_app_features"]:
        assert a["addiction_model_score"] is None
        assert a["distraction_model_score"] is None
    assert "train_cli" in body["scoring_message"]


def test_simulate_day_uses_trained_models_from_registry(monkeypatch, tmp_path):
    import pytest

    pytest.importorskip("lightgbm")
    import mock_backend.main as backend
    from attention_tracker.models.lightgbm_scorer import train_model
    from attention_tracker.models.registry import save_model
    from attention_tracker.models.synthetic_dataset import (
        SyntheticDatasetConfig,
        build_synthetic_distillation_dataset,
    )

    dataset = build_synthetic_distillation_dataset(
        SyntheticDatasetConfig(seeds_per_archetype=4, num_days=7)
    )
    for kind in ("addiction", "distraction"):
        save_model(train_model(dataset, kind=kind, seed=0), root=tmp_path, version="v-test")

    monkeypatch.setenv("ATTENTION_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(backend, "_models", {})

    body = client.post("/simulate-day", json={"archetype": "DOOMSCROLLER"}).json()

    assert body["scoring_status"] == "models_loaded"
    assert body["model_versions"] == {"addiction": "v-test", "distraction": "v-test"}
    for a in body["per_app_features"]:
        assert 0.0 <= a["addiction_model_score"] <= 10.0
        assert 0.0 <= a["distraction_model_score"] <= 10.0