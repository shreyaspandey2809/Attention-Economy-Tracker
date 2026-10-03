import math

from attention_tracker.models.dataset import COLUMN_NAMES
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)
from attention_tracker.synthetic.archetypes import BALANCED, DOOMSCROLLER


def _rows_equal_nan_aware(rows_a, rows_b) -> bool:
    if len(rows_a) != len(rows_b):
        return False
    for row_a, row_b in zip(rows_a, rows_b):
        for a, b in zip(row_a, row_b):
            if math.isnan(a) and math.isnan(b):
                continue
            if a != b:
                return False
    return True


def test_builds_nonempty_dataset():
    config = SyntheticDatasetConfig(seeds_per_archetype=2, num_days=7)
    ds = build_synthetic_distillation_dataset(config)
    assert len(ds) > 0


def test_rows_match_column_width():
    config = SyntheticDatasetConfig(seeds_per_archetype=2, num_days=7)
    ds = build_synthetic_distillation_dataset(config)
    for row in ds.rows:
        assert len(row) == len(COLUMN_NAMES)


def test_targets_are_in_heuristic_range():
    config = SyntheticDatasetConfig(seeds_per_archetype=2, num_days=7)
    ds = build_synthetic_distillation_dataset(config)
    assert all(0.0 <= t <= 10.0 for t in ds.targets)


def test_groups_are_per_synthetic_user_not_per_row():
    config = SyntheticDatasetConfig(
        seeds_per_archetype=3, num_days=7, archetypes=(BALANCED,)
    )
    ds = build_synthetic_distillation_dataset(config)
    assert len(set(ds.groups)) == 3
    assert len(ds.groups) > 3  # multiple windows per synthetic user


def test_deterministic_given_same_config():
    config = SyntheticDatasetConfig(seeds_per_archetype=2, num_days=7, archetypes=(DOOMSCROLLER,))
    ds1 = build_synthetic_distillation_dataset(config)
    ds2 = build_synthetic_distillation_dataset(config)
    assert _rows_equal_nan_aware(ds1.rows, ds2.rows)
    assert ds1.targets == ds2.targets
    assert ds1.groups == ds2.groups


def test_seed_offset_produces_disjoint_users():
    config = SyntheticDatasetConfig(seeds_per_archetype=2, num_days=7, archetypes=(BALANCED,))
    ds_a = build_synthetic_distillation_dataset(config, seed_offset=0)
    ds_b = build_synthetic_distillation_dataset(config, seed_offset=1000)
    assert set(ds_a.groups).isdisjoint(set(ds_b.groups))