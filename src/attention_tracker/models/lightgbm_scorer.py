from dataclasses import dataclass
from typing import Literal

import numpy as np

from attention_tracker.evaluation.validation import DistillationReport, distillation_report
from attention_tracker.models.dataset import COLUMN_NAMES, Dataset

ModelKind = Literal["addiction", "distraction"]

_DISTRACTION_EXCLUDED_COLUMNS = frozenset({"session_count", "sessions_under_30s_ratio"})

MAX_BOOST_ROUNDS = 2000
EARLY_STOPPING_ROUNDS = 50
EARLY_STOPPING_MIN_DELTA = 1e-3

DEFAULT_LGB_PARAMS: dict[str, object] = {
    "objective": "regression",
    "metric": "l2",
    "num_leaves": 15,
    "min_data_in_leaf": 20,
    "learning_rate": 0.05,
    "verbose": -1,
    "seed": 0,
}


def _columns_for_kind(kind: ModelKind) -> list[str]:
    if kind == "distraction":
        return [c for c in COLUMN_NAMES if c not in _DISTRACTION_EXCLUDED_COLUMNS]
    return list(COLUMN_NAMES)


def group_train_test_split(
    dataset: Dataset, test_fraction: float = 0.2, seed: int = 0
) -> tuple[list[int], list[int]]:
    import random

    unique_groups = sorted(set(dataset.groups))
    rng = random.Random(seed)
    rng.shuffle(unique_groups)

    n_test_groups = max(1, round(len(unique_groups) * test_fraction))
    test_groups = set(unique_groups[:n_test_groups])
    train_groups = set(unique_groups[n_test_groups:])

    if not train_groups or not test_groups:
        raise ValueError(
            f"(train={len(train_groups)} groups, test={len(test_groups)} groups); "
        )

    train_idx = [i for i, g in enumerate(dataset.groups) if g in train_groups]
    test_idx = [i for i, g in enumerate(dataset.groups) if g in test_groups]
    return train_idx, test_idx


def group_train_val_test_split(
    dataset: Dataset,
    val_fraction: float = 0.2,
    test_fraction: float = 0.2,
    seed: int = 0,
) -> tuple[list[int], list[int], list[int]]:
    import random

    unique_groups = sorted(set(dataset.groups))
    rng = random.Random(seed)
    rng.shuffle(unique_groups)

    n = len(unique_groups)
    n_test = max(1, round(n * test_fraction))
    n_val = max(1, round(n * val_fraction))
    if n - n_test - n_val < 1:
        raise ValueError(
            "group_train_val_test_split produced an empty train side "
            f"({n} users, val_fraction={val_fraction}, test_fraction={test_fraction}); "
            "widen the dataset or shrink the fractions"
        )

    test_groups = set(unique_groups[:n_test])
    val_groups = set(unique_groups[n_test : n_test + n_val])
    train_groups = set(unique_groups[n_test + n_val :])

    train_idx = [i for i, g in enumerate(dataset.groups) if g in train_groups]
    val_idx = [i for i, g in enumerate(dataset.groups) if g in val_groups]
    test_idx = [i for i, g in enumerate(dataset.groups) if g in test_groups]
    return train_idx, val_idx, test_idx


@dataclass
class TrainedModel:

    booster: object
    kind: ModelKind
    columns: list[str]

    def predict(self, rows: list[list[float]]) -> list[float]:
        if not rows:
            # np.array([]) has shape (0,), which lgb.Booster.predict()
            # rejects as not 2-dimensional — short-circuit instead.
            return []
        col_indices = [COLUMN_NAMES.index(c) for c in self.columns]
        subset = np.array(
            [[row[i] for i in col_indices] for row in rows], dtype=float
        )
        return [float(p) for p in self.booster.predict(subset)]


@dataclass(frozen=True)
class TrainResult:
    model: TrainedModel
    train_distillation: DistillationReport
    val_distillation: DistillationReport
    test_distillation: DistillationReport
    best_iteration: int


def train_model(
    dataset: Dataset,
    kind: ModelKind = "addiction",
    test_fraction: float = 0.2,
    seed: int = 0,
    params: dict[str, object] | None = None,
    val_fraction: float = 0.2,
) -> TrainResult:
    import lightgbm as lgb

    columns = _columns_for_kind(kind)
    col_indices = [COLUMN_NAMES.index(c) for c in columns]

    train_idx, val_idx, test_idx = group_train_val_test_split(
        dataset, val_fraction, test_fraction, seed
    )

    x_train = np.array(
        [[dataset.rows[i][c] for c in col_indices] for i in train_idx], dtype=float
    )
    y_train = np.array([dataset.targets[i] for i in train_idx], dtype=float)
    x_val = np.array(
        [[dataset.rows[i][c] for c in col_indices] for i in val_idx], dtype=float
    )
    y_val = np.array([dataset.targets[i] for i in val_idx], dtype=float)

    train_data = lgb.Dataset(x_train, label=y_train, feature_name=columns)
    valid_data = lgb.Dataset(x_val, label=y_val, feature_name=columns, reference=train_data)

    merged_params = dict(DEFAULT_LGB_PARAMS)
    merged_params["seed"] = seed
    if params:
        merged_params.update(params)

    booster = lgb.train(
        merged_params,
        train_data,
        num_boost_round=MAX_BOOST_ROUNDS,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(
                stopping_rounds=EARLY_STOPPING_ROUNDS,
                min_delta=EARLY_STOPPING_MIN_DELTA,
                verbose=False,
            )],
    )

    model = TrainedModel(booster=booster, kind=kind, columns=columns)

    # Always score predict() against FULL-WIDTH rows — predict() owns
    # the column re-indexing, so it must never be fed the already
    # column-subsetted x_train/x_val arrays used for lgb.Dataset above.
    train_pred = model.predict([dataset.rows[i] for i in train_idx])
    val_pred = model.predict([dataset.rows[i] for i in val_idx])
    test_pred = model.predict([dataset.rows[i] for i in test_idx])

    train_report = distillation_report([dataset.targets[i] for i in train_idx], train_pred)
    val_report = distillation_report([dataset.targets[i] for i in val_idx], val_pred)
    test_report = distillation_report([dataset.targets[i] for i in test_idx], test_pred)

    return TrainResult(
        model=model,
        train_distillation=train_report,
        val_distillation=val_report,
        test_distillation=test_report,
        best_iteration=int(booster.best_iteration),
    )


def retarget_dataset(dataset: Dataset, user_labels: dict[str, float]) -> Dataset:
    rows: list[list[float]] = []
    targets: list[float] = []
    groups: list[str] = []

    for row, group in zip(dataset.rows, dataset.groups):
        if group in user_labels:
            rows.append(row)
            targets.append(user_labels[group])
            groups.append(group)

    if not rows:
        raise ValueError("no rows matched any user_labels key")

    return Dataset(rows=rows, targets=targets, groups=groups, column_names=dataset.column_names)