import pytest

lgb_testing = pytest.importorskip("lightgbm", reason="lightgbm not installed; M5 tests need it")

from attention_tracker.models.dataset import Dataset
from attention_tracker.models.lightgbm_scorer import train_model
from attention_tracker.models.model_evaluation import (
    EXPECTED_RISK_ORDER,
    archetype_ranking_check,
    correlation_against_heuristic,
    stability_under_perturbation,
)
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)

DATASET = build_synthetic_distillation_dataset(
    SyntheticDatasetConfig(seeds_per_archetype=8, num_days=21)
)


@pytest.fixture(scope="module")
def trained():
    return train_model(DATASET, kind="addiction", seed=0)


def test_archetype_ranking_preserves_expected_order(trained):
    result = archetype_ranking_check(trained.model, seeds_per_archetype=8, num_days=21)
    assert result.preserves_expected_order
    assert isinstance(result.preserves_expected_order, bool)


def test_archetype_ranking_covers_expected_archetypes(trained):
    result = archetype_ranking_check(trained.model, seeds_per_archetype=8, num_days=21)
    for name in EXPECTED_RISK_ORDER:
        assert name in result.mean_score_by_archetype
        assert isinstance(result.mean_score_by_archetype[name], float)


def test_correlation_against_heuristic_is_strong(trained):
    result = correlation_against_heuristic(trained.model, DATASET.rows, DATASET.targets)
    assert result.spearman_rho is not None
    assert result.spearman_rho > 0.9
    assert result.n_windows == len(DATASET)


def test_correlation_raises_on_length_mismatch(trained):
    with pytest.raises(ValueError):
        correlation_against_heuristic(trained.model, DATASET.rows, DATASET.targets[:5])


def test_empty_rows_gives_undefined_correlation(trained):
    result = correlation_against_heuristic(trained.model, [], [])
    assert result.spearman_rho is None
    assert result.n_windows == 0


def test_ordering_survives_moderate_noise(trained):
    def train_fn(rows, targets, groups):
        ds = Dataset(rows=rows, targets=targets, groups=groups)
        return train_model(ds, kind="addiction", seed=0).model

    result = stability_under_perturbation(
        train_fn,
        DATASET.rows,
        DATASET.targets,
        DATASET.groups,
        noise_fraction=1.0,
        n_perturbations=3,
        seed=1,
    )
    assert result.all_passed
    assert result.total_perturbations == 3


def test_stability_result_reports_failures_list(trained):
    def always_same_train_fn(rows, targets, groups):
        ds = Dataset(rows=rows, targets=targets, groups=groups)
        return train_model(ds, kind="addiction", seed=0).model

    result = stability_under_perturbation(
        always_same_train_fn,
        DATASET.rows,
        DATASET.targets,
        DATASET.groups,
        noise_fraction=0.05,
        n_perturbations=2,
        seed=2,
    )
    assert isinstance(result.failures, list)
    assert result.passed_perturbations + len(result.failures) == result.total_perturbations