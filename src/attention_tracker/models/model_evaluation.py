from dataclasses import dataclass
from typing import Callable

from attention_tracker.evaluation.validation import spearman
from attention_tracker.models.lightgbm_scorer import TrainedModel
from attention_tracker.models.synthetic_dataset import SyntheticDatasetConfig, build_synthetic_distillation_dataset

EXPECTED_RISK_ORDER: tuple[str, ...] = ("COMPULSIVE_CHECKER", "DOOMSCROLLER", "DEEP_WORKER")

_HELD_OUT_SEED_OFFSET = 1000


@dataclass(frozen=True)
class ArchetypeRankingResult:
    mean_score_by_archetype: dict[str, float]
    preserves_expected_order: bool


def archetype_ranking_check(
    model: TrainedModel,
    taxonomy=None,
    seeds_per_archetype: int = 10,
    num_days: int = 21,
) -> ArchetypeRankingResult:
    from attention_tracker.synthetic.archetypes import ARCHETYPES

    config_kwargs: dict[str, object] = {
        "seeds_per_archetype": seeds_per_archetype,
        "num_days": num_days,
    }
    if taxonomy is not None:
        config_kwargs["taxonomy"] = taxonomy
    config = SyntheticDatasetConfig(**config_kwargs)

    mean_score_by_archetype: dict[str, float] = {}
    for archetype_name, archetype in ARCHETYPES.items():
        single_config = SyntheticDatasetConfig(
            seeds_per_archetype=config.seeds_per_archetype,
            num_days=config.num_days,
            start_date_iso=config.start_date_iso,
            taxonomy=config.taxonomy,
            archetypes=(archetype,),
        )
        held_out = build_synthetic_distillation_dataset(
            single_config, seed_offset=_HELD_OUT_SEED_OFFSET
        )
        if not held_out.rows:
            continue
        predictions = model.predict(held_out.rows)
        mean_score_by_archetype[archetype_name] = float(
            sum(predictions) / len(predictions)
        )

    order_scores = [
        mean_score_by_archetype[name]
        for name in EXPECTED_RISK_ORDER
        if name in mean_score_by_archetype
    ]
    preserves_order = bool(
        len(order_scores) == len(EXPECTED_RISK_ORDER)
        and all(order_scores[i] >= order_scores[i + 1] for i in range(len(order_scores) - 1))
    )

    return ArchetypeRankingResult(
        mean_score_by_archetype=mean_score_by_archetype,
        preserves_expected_order=preserves_order,
    )


@dataclass(frozen=True)
class HeuristicCorrelationResult:
    spearman_rho: float | None
    n_windows: int


def correlation_against_heuristic(
    model: TrainedModel,
    rows: list[list[float]],
    heuristic_scores: list[float],
) -> HeuristicCorrelationResult:
    if len(rows) != len(heuristic_scores):
        raise ValueError("rows and heuristic_scores must have the same length")
    predictions = model.predict(rows)
    rho = spearman(predictions, heuristic_scores) if rows else None
    return HeuristicCorrelationResult(spearman_rho=rho, n_windows=len(rows))


@dataclass(frozen=True)
class StabilityResult:
    passed_perturbations: int
    total_perturbations: int
    failures: list[int]

    @property
    def all_passed(self) -> bool:
        return self.passed_perturbations == self.total_perturbations


def stability_under_perturbation(
    train_fn: Callable[[list[list[float]], list[float], list[str]], TrainedModel],
    rows: list[list[float]],
    targets: list[float],
    groups: list[str],
    noise_fraction: float = 1.0,
    n_perturbations: int = 5,
    seed: int = 0,
) -> StabilityResult:
    import random

    from attention_tracker.models.model_evaluation import archetype_ranking_check  # self-import for clarity of call site

    rng = random.Random(seed)
    n_cols = len(rows[0]) if rows else 0

    col_stdevs: list[float] = []
    for c in range(n_cols):
        values = [row[c] for row in rows if row[c] == row[c]]  # filter NaN
        if len(values) < 2:
            col_stdevs.append(0.0)
            continue
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        col_stdevs.append(variance**0.5)

    failures: list[int] = []
    for trial in range(n_perturbations):
        noised_rows = []
        for row in rows:
            noised_row = [
                v
                if v != v  # NaN stays NaN — never inject noise into "undefined"
                else v + rng.gauss(0, col_stdevs[c] * noise_fraction)
                for c, v in enumerate(row)
            ]
            noised_rows.append(noised_row)

        model = train_fn(noised_rows, targets, groups)
        result = archetype_ranking_check(model)
        if not result.preserves_expected_order:
            failures.append(trial)

    return StabilityResult(
        passed_perturbations=n_perturbations - len(failures),
        total_perturbations=n_perturbations,
        failures=failures,
    )