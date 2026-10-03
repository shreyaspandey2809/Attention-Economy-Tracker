import math

import pytest

from attention_tracker.models.dataset import COLUMN_NAMES, Dataset, feature_row
from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory


def _fv(**overrides) -> FeatureVector:
    defaults = dict(
        user_id="u1",
        package_name="com.example.app",
        total_time_sec=600.0,
        session_count=5,
        avg_session_duration_sec=120.0,
        max_session_duration_sec=300.0,
        sessions_under_30s_ratio=0.2,
        interarrival_mean_sec=90.0,
        interarrival_under_2min_ratio=0.5,
        late_night_usage_pct=0.1,
        late_night_usage_time_ratio=0.1,
        hourly_usage_entropy=0.7,
        weekend_usage_ratio=0.3,
        productive_interruption_rate=0.4,
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


def test_column_names_fixed_width():
    # 12 engineered features + 6 one-hot category columns.
    assert len(COLUMN_NAMES) == 12 + 6


def test_feature_row_matches_column_count():
    row = feature_row(_fv(), AppCategory.ADDICTIVE)
    assert len(row) == len(COLUMN_NAMES)


def test_feature_row_undefined_features_are_nan_not_zero():
    fv = _fv(interarrival_mean_sec=None, interarrival_under_2min_ratio=None)
    row = feature_row(fv, AppCategory.PRODUCTIVE)
    idx_mean = COLUMN_NAMES.index("interarrival_mean_sec")
    idx_ratio = COLUMN_NAMES.index("interarrival_under_2min_ratio")
    assert math.isnan(row[idx_mean])
    assert math.isnan(row[idx_ratio])


def test_feature_row_defined_features_are_not_nan():
    row = feature_row(_fv(), AppCategory.ADDICTIVE)
    idx_mean = COLUMN_NAMES.index("interarrival_mean_sec")
    assert row[idx_mean] == 90.0


def test_feature_row_one_hot_category_correct():
    row = feature_row(_fv(), AppCategory.ENTERTAINMENT)
    for category in AppCategory:
        col = f"category_{category.value}"
        if col not in COLUMN_NAMES:
            continue
        idx = COLUMN_NAMES.index(col)
        expected = 1.0 if category == AppCategory.ENTERTAINMENT else 0.0
        assert row[idx] == expected


def test_feature_row_one_hot_sums_to_one():
    row = feature_row(_fv(), AppCategory.UTILITY)
    category_cols = [i for i, c in enumerate(COLUMN_NAMES) if c.startswith("category_")]
    assert sum(row[i] for i in category_cols) == 1.0


def test_dataset_valid_construction():
    rows = [feature_row(_fv(), AppCategory.ADDICTIVE) for _ in range(3)]
    ds = Dataset(rows=rows, targets=[1.0, 2.0, 3.0], groups=["u1", "u1", "u2"])
    assert len(ds) == 3


def test_dataset_rejects_mismatched_target_length():
    rows = [feature_row(_fv(), AppCategory.ADDICTIVE)]
    with pytest.raises(ValueError):
        Dataset(rows=rows, targets=[1.0, 2.0], groups=["u1"])


def test_dataset_rejects_mismatched_group_length():
    rows = [feature_row(_fv(), AppCategory.ADDICTIVE)]
    with pytest.raises(ValueError):
        Dataset(rows=rows, targets=[1.0], groups=["u1", "u2"])


def test_dataset_rejects_wrong_row_width():
    bad_row = [0.0] * (len(COLUMN_NAMES) - 1)
    with pytest.raises(ValueError):
        Dataset(rows=[bad_row], targets=[1.0], groups=["u1"])