import random
import statistics
from datetime import datetime, timezone

import pytest

from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.config import DEFAULT_WEIGHTS, HeuristicWeights
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.synthetic.archetypes import (
    ARCHETYPES,
    BALANCED,
    BINGE_WEEKEND,
    COMPULSIVE_CHECKER,
    DEEP_WORKER,
    DOOMSCROLLER,
)
from attention_tracker.synthetic.generator import SyntheticEventGenerator

START = datetime(2026, 8, 3, tzinfo=timezone.utc)
NUM_DAYS = 14
SEEDS = range(30)

REQUIRED_PASS_RATE = 27


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


def _mean_score_for_seed(profile, seed: int, taxonomy: TaxonomyLoader) -> float:
    gen = SyntheticEventGenerator(rng=random.Random(seed))
    events = gen.generate("u1", profile, START, num_days=NUM_DAYS)
    result = run_data_quality_pipeline(events)
    windows = group_sessions_by_user_app_day(result.sessions)
    scores = []
    for sessions in windows.values():
        fv = build_feature_vector(sessions, taxonomy)
        category = taxonomy.lookup(fv.package_name).category
        scores.append(compute_heuristic_score(fv, category))
    return statistics.mean(scores) if scores else 0.0


class TestWeightsAreValid:
    def test_default_weights_sum_to_one(self):
        total = (
            DEFAULT_WEIGHTS.total_time_sec
            + DEFAULT_WEIGHTS.session_count
            + DEFAULT_WEIGHTS.sessions_under_30s_ratio
            + DEFAULT_WEIGHTS.interarrival_under_2min_ratio
            + DEFAULT_WEIGHTS.late_night_usage_pct
            + DEFAULT_WEIGHTS.weekend_usage_ratio
            + DEFAULT_WEIGHTS.hourly_usage_entropy
            + DEFAULT_WEIGHTS.productive_interruption_rate
        )
        assert total == pytest.approx(1.0)

    def test_weights_not_summing_to_one_raises(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            HeuristicWeights(total_time_sec=0.5, session_count=0.5, sessions_under_30s_ratio=0.5)


class TestArchetypeOrdering:

    def test_doomscroller_outscores_balanced(self, taxonomy):
        passes = sum(
            1
            for seed in SEEDS
            if _mean_score_for_seed(DOOMSCROLLER, seed, taxonomy)
            > _mean_score_for_seed(BALANCED, seed, taxonomy)
        )
        assert passes >= REQUIRED_PASS_RATE, (
            f"DOOMSCROLLER > BALANCED only held {passes}/{len(SEEDS)} seeds"
        )

    def test_compulsive_checker_outscores_doomscroller(self, taxonomy):
        passes = sum(
            1
            for seed in SEEDS
            if _mean_score_for_seed(COMPULSIVE_CHECKER, seed, taxonomy)
            > _mean_score_for_seed(DOOMSCROLLER, seed, taxonomy)
        )
        assert passes >= REQUIRED_PASS_RATE, (
            f"COMPULSIVE_CHECKER > DOOMSCROLLER only held {passes}/{len(SEEDS)} seeds"
        )

    def test_doomscroller_outscores_deep_worker(self, taxonomy):
        passes = sum(
            1
            for seed in SEEDS
            if _mean_score_for_seed(DOOMSCROLLER, seed, taxonomy)
            > _mean_score_for_seed(DEEP_WORKER, seed, taxonomy)
        )
        assert passes >= REQUIRED_PASS_RATE, (
            f"DOOMSCROLLER > DEEP_WORKER only held {passes}/{len(SEEDS)} seeds"
        )

    def test_binge_weekend_outscores_balanced(self, taxonomy):
        passes = sum(
            1
            for seed in SEEDS
            if _mean_score_for_seed(BINGE_WEEKEND, seed, taxonomy)
            > _mean_score_for_seed(BALANCED, seed, taxonomy)
        )
        assert passes >= REQUIRED_PASS_RATE, (
            f"BINGE_WEEKEND > BALANCED only held {passes}/{len(SEEDS)} seeds"
        )

    def test_compulsive_checker_outscores_all_others(self, taxonomy):
        others = [BALANCED, DOOMSCROLLER, BINGE_WEEKEND, DEEP_WORKER]
        for other in others:
            passes = sum(
                1
                for seed in SEEDS
                if _mean_score_for_seed(COMPULSIVE_CHECKER, seed, taxonomy)
                > _mean_score_for_seed(other, seed, taxonomy)
            )
            assert passes >= REQUIRED_PASS_RATE, (
                f"COMPULSIVE_CHECKER > {other.name} only held "
                f"{passes}/{len(SEEDS)} seeds"
            )


class TestScoreRange:
    def test_score_is_always_between_0_and_10(self, taxonomy):
        for name, profile in ARCHETYPES.items():
            for seed in range(5):
                gen = SyntheticEventGenerator(rng=random.Random(seed))
                events = gen.generate("u1", profile, START, num_days=NUM_DAYS)
                result = run_data_quality_pipeline(events)
                windows = group_sessions_by_user_app_day(result.sessions)
                for sessions in windows.values():
                    fv = build_feature_vector(sessions, taxonomy)
                    category = taxonomy.lookup(fv.package_name).category
                    score = compute_heuristic_score(fv, category)
                    assert 0.0 <= score <= 10.0, (
                        f"{name} produced out-of-range score {score}"
                    )