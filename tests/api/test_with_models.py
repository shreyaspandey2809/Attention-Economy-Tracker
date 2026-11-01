import pytest

pytest.importorskip("lightgbm", reason="lightgbm not installed; model-backed API tests need it")

from fastapi.testclient import TestClient

from attention_tracker.api.app import create_app
from attention_tracker.api.auth import issue_device
from attention_tracker.models.lightgbm_scorer import train_model
from attention_tracker.models.registry import save_model
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)
from tests.api.conftest import payload


@pytest.fixture(scope="module")
def trained():
    ds = build_synthetic_distillation_dataset(SyntheticDatasetConfig(seeds_per_archetype=5, num_days=10))
    return {k: train_model(ds, kind=k, seed=0) for k in ("addiction", "distraction")}


@pytest.fixture
def registry(tmp_path, trained):
    root = tmp_path / "registry"
    for result in trained.values():
        save_model(result, root=root, version="20260101T000000Z")
    return root


def _setup(registry, make_events):
    client = TestClient(create_app(db_path=":memory:", model_dir=registry))
    _id, token = issue_device(client.app.state.repo, "u1")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/v1/consent", headers=headers)
    client.post("/v1/events", json=payload(make_events("u1")), headers=headers)
    return client, headers


def test_scores_include_model_outputs_and_versions(registry, make_events):
    client, headers = _setup(registry, make_events)
    body = client.get("/v1/users/u1/scores", headers=headers).json()

    assert body["scoring_status"] == "models_loaded"
    assert body["model_versions"] == {"addiction": "20260101T000000Z", "distraction": "20260101T000000Z"}
    for a in body["apps"]:
        assert 0 <= a["addiction_model_score"] <= 10
        assert 0 <= a["distraction_model_score"] <= 10
        assert a["addiction_model_version"] == "20260101T000000Z"
    for d in body["daily"]:
        assert 0 <= d["addiction_model_score"] <= 10


def test_model_scores_agree_with_a_direct_prediction(registry, make_events):
    from attention_tracker.models.dataset import feature_row
    from attention_tracker.models.registry import load_latest
    from attention_tracker.pipeline.features.feature_vector import build_feature_vector
    from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
    from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
    from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

    client, headers = _setup(registry, make_events)
    stored = {(a["package_name"], a["day"]): a["addiction_model_score"]
              for a in client.get("/v1/users/u1/scores", headers=headers).json()["apps"]}

    tax = TaxonomyLoader(include_extended=True)
    model, _rec = load_latest("addiction", registry)
    result = run_data_quality_pipeline(make_events("u1"), taxonomy=tax)
    for (_u, pkg, day), group in group_sessions_by_user_app_day(result.sessions).items():
        fv = build_feature_vector(group, tax)
        row = feature_row(fv, tax.lookup(pkg).category)
        expected = max(0.0, min(10.0, model.predict([row])[0]))
        assert stored[(pkg, day.isoformat())] == pytest.approx(expected)


def test_models_endpoint_lists_both_kinds_with_caveat(registry, make_events):
    client, headers = _setup(registry, make_events)
    models = client.get("/v1/models", headers=headers).json()["models"]

    assert {m["kind"] for m in models} == {"addiction", "distraction"}
    assert all(m["caveat"] and m["test_r_squared"] is not None for m in models)


def test_newly_trained_model_is_used_on_next_scoring_run(registry, trained, make_events):
    client, headers = _setup(registry, make_events)
    client.get("/v1/users/u1/scores", headers=headers)

    for result in trained.values():
        save_model(result, root=registry, version="20260202T000000Z")
    client.post("/v1/events", json=payload(make_events("u1", num_days=3)), headers=headers)  # marks stale

    body = client.get("/v1/users/u1/scores", headers=headers).json()
    assert body["model_versions"]["addiction"] == "20260202T000000Z"
    assert {a["addiction_model_version"] for a in body["apps"]} == {"20260202T000000Z"}
