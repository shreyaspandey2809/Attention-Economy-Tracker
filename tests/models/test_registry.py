import json

import pytest

pytest.importorskip("lightgbm", reason="lightgbm not installed; registry tests need it")

from attention_tracker.models.lightgbm_scorer import train_model
from attention_tracker.models.registry import (
    REGISTRY_ENV_VAR,
    default_registry_dir,
    latest_record,
    list_versions,
    load_latest,
    load_model,
    save_model,
)
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)


@pytest.fixture(scope="module")
def dataset():
    return build_synthetic_distillation_dataset(
        SyntheticDatasetConfig(seeds_per_archetype=5, num_days=10)
    )


@pytest.fixture(scope="module")
def trained(dataset):
    return train_model(dataset, kind="distraction", seed=0)


def test_save_then_load_reproduces_predictions(trained, dataset, tmp_path):
    record = save_model(trained, root=tmp_path, version="v1")
    loaded = load_model(record.path)

    rows = dataset.rows[:25]
    assert loaded.kind == "distraction"
    assert loaded.predict(rows) == pytest.approx(trained.model.predict(rows))


def test_meta_records_provenance_and_caveat(trained, tmp_path):
    record = save_model(trained, root=tmp_path, version="v1", extra_meta={"seed": 0})
    meta = json.loads((record.path / "meta.json").read_text())

    assert meta["kind"] == "distraction"
    assert meta["version"] == "v1"
    assert meta["target"] == "heuristic_distillation_synthetic"
    assert meta["seed"] == 0
    assert meta["columns"] == list(trained.model.columns)
    assert meta["best_iteration"] == trained.best_iteration
    assert "REPRODUCES" in meta["caveat"]


def test_saving_same_version_twice_is_refused(trained, tmp_path):
    save_model(trained, root=tmp_path, version="v1")
    with pytest.raises(FileExistsError):
        save_model(trained, root=tmp_path, version="v1")


def test_latest_is_lexicographically_newest(trained, tmp_path):
    save_model(trained, root=tmp_path, version="20260101T000000Z")
    save_model(trained, root=tmp_path, version="20260301T000000Z")
    save_model(trained, root=tmp_path, version="20260201T000000Z")

    assert [r.version for r in list_versions("distraction", tmp_path)] == [
        "20260101T000000Z",
        "20260201T000000Z",
        "20260301T000000Z",
    ]
    assert latest_record("distraction", tmp_path).version == "20260301T000000Z"


def test_load_latest_returns_none_when_registry_empty(tmp_path):
    assert load_latest("addiction", tmp_path) is None
    assert latest_record("addiction", tmp_path / "does_not_exist") is None


def test_load_refuses_model_with_unknown_columns(trained, tmp_path):
    record = save_model(trained, root=tmp_path, version="v1")
    meta_path = record.path / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["columns"] = meta["columns"] + ["a_column_that_was_removed"]
    meta_path.write_text(json.dumps(meta))

    with pytest.raises(ValueError, match="retrain"):
        load_model(record.path)


def test_default_registry_dir_honours_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(REGISTRY_ENV_VAR, str(tmp_path))
    assert default_registry_dir() == tmp_path