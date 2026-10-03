import pytest

lgb_testing = pytest.importorskip("lightgbm", reason="lightgbm not installed; M5 tests need it")

from attention_tracker.models.dataset import COLUMN_NAMES, Dataset
from attention_tracker.models.lightgbm_scorer import (
    DEFAULT_LGB_PARAMS,
    group_train_test_split,
    retarget_dataset,
    train_model,
)
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    config = SyntheticDatasetConfig(seeds_per_archetype=6, num_days=14)
    return build_synthetic_distillation_dataset(config)


def test_group_split_no_user_overlap(dataset):
    train_idx, test_idx = group_train_test_split(dataset, test_fraction=0.25, seed=0)
    train_groups = {dataset.groups[i] for i in train_idx}
    test_groups = {dataset.groups[i] for i in test_idx}
    assert train_groups.isdisjoint(test_groups)
    assert train_idx
    assert test_idx


def test_group_split_covers_all_rows(dataset):
    train_idx, test_idx = group_train_test_split(dataset, test_fraction=0.25, seed=0)
    assert len(train_idx) + len(test_idx) == len(dataset)


def test_group_split_raises_on_empty_side():
    ds = Dataset(
        rows=[[0.0] * len(COLUMN_NAMES)],
        targets=[1.0],
        groups=["only_user"],
    )
    with pytest.raises(ValueError):
        group_train_test_split(ds, test_fraction=0.5, seed=0)


def test_train_addiction_model_runs(dataset):
    result = train_model(dataset, kind="addiction", seed=0)
    assert result.train_distillation.n_windows > 0
    assert result.test_distillation.n_windows > 0
    assert result.test_distillation.r_squared is not None
    assert result.test_distillation.r_squared > 0.5


def test_train_distraction_model_runs(dataset):
    result = train_model(dataset, kind="distraction", seed=0)
    assert result.model.kind == "distraction"
    assert result.test_distillation.r_squared is not None


def test_distillation_report_carries_caveat(dataset):
    result = train_model(dataset, kind="addiction", seed=0)
    assert "REPRODUCES" in result.test_distillation.caveat
    assert "not" in result.test_distillation.caveat.lower()


def test_predict_accepts_full_width_rows_for_distraction_model(dataset):
    result = train_model(dataset, kind="distraction", seed=0)
    full_width_row = dataset.rows[0]
    assert len(full_width_row) == len(COLUMN_NAMES)
    predictions = result.model.predict([full_width_row])
    assert len(predictions) == 1


def test_predict_empty_rows_returns_empty_list(dataset):
    result = train_model(dataset, kind="addiction", seed=0)
    assert result.model.predict([]) == []


def test_retarget_dataset_swaps_target(dataset):
    some_user = dataset.groups[0]
    retargeted = retarget_dataset(dataset, {some_user: 42.0})
    assert all(g == some_user for g in retargeted.groups)
    assert all(t == 42.0 for t in retargeted.targets)


def test_retarget_dataset_drops_unlabeled_users(dataset):
    some_user = dataset.groups[0]
    retargeted = retarget_dataset(dataset, {some_user: 5.0})
    assert len(retargeted) < len(dataset)


def test_retarget_dataset_raises_when_no_match(dataset):
    with pytest.raises(ValueError):
        retarget_dataset(dataset, {"nonexistent_user": 1.0})


def test_default_params_is_regression_objective():
    assert DEFAULT_LGB_PARAMS["objective"] == "regression"