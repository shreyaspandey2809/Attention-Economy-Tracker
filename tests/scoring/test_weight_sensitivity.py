import random
import statistics
from dataclasses import fields, replace
from datetime import datetime, timezone

import pytest

from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.config import DEFAULT_WEIGHTS, HeuristicWeights
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.synthetic.archetypes import COMPULSIVE_CHECKER, DEEP_WORKER, DOOMSCROLLER
from attention_tracker.synthetic.generator import SyntheticEventGenerator

START = datetime(2026, 8, 3, tzinfo=timezone.utc)
NUM_DAYS = 14
SENSITIVITY_SEEDS = range(10)
PERTURBATION_FRACTION = 0.25


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


def _perturb_weight(field_name: str, direction: float) -> HeuristicWeights:
    current = getattr(DEFAULT_WEIGHTS, field_name)
    delta = current * PERTURBATION_FRACTION * direction
    new_value = current + delta

    other_fields = [f.name for f in fields(DEFAULT_WEIGHTS) if f.name != field_name]
    other_total = sum(getattr(DEFAULT_WEIGHTS, f) for f in other_fields)

    updates = {field_name: new_value}
    for f in other_fields:
        share = getattr(DEFAULT_WEIGHTS, f) / other_total
        updates[f] = getattr(DEFAULT_WEIGHTS, f) - delta * share

    return replace(DEFAULT_WEIGHTS, **updates)


def _mean_score(profile, weights: HeuristicWeights, taxonomy: TaxonomyLoader) -> float:
    scores = []
    for seed in SENSITIVITY_SEEDS:
        gen = SyntheticEventGenerator(rng=random.Random(seed))
        events = gen.generate("u1", profile, START, num_days=NUM_DAYS)
        result = run_data_quality_pipeline(events)
        windows = group_sessions_by_user_app_day(result.sessions)
        for sessions in windows.values():
            fv = build_feature_vector(sessions, taxonomy)
            category = taxonomy.lookup(fv.package_name).category
            scores.append(compute_heuristic_score(fv, category, weights=weights))
    return statistics.mean(scores) if scores else 0.0


WEIGHT_FIELD_NAMES = [f.name for f in fields(HeuristicWeights)]


class TestWeightPerturbationStability:

    @pytest.mark.parametrize("field_name", WEIGHT_FIELD_NAMES)
    @pytest.mark.parametrize("direction", [1.0, -1.0], ids=["increased", "decreased"])
    def test_ordering_survives_single_weight_perturbation(
        self, field_name, direction, taxonomy
    ):
        perturbed = _perturb_weight(field_name, direction)

        cc_score = _mean_score(COMPULSIVE_CHECKER, perturbed, taxonomy)
        doom_score = _mean_score(DOOMSCROLLER, perturbed, taxonomy)
        deep_score = _mean_score(DEEP_WORKER, perturbed, taxonomy)

        assert cc_score > doom_score > deep_score, (
            f"Ordering broke when {field_name} was "
            f"{'increased' if direction > 0 else 'decreased'} by "
            f"{PERTURBATION_FRACTION:.0%}: "
            f"COMPULSIVE_CHECKER={cc_score:.2f}, "
            f"DOOMSCROLLER={doom_score:.2f}, DEEP_WORKER={deep_score:.2f}"
        )