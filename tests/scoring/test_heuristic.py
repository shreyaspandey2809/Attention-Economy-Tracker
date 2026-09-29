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


def _mean_score_for_seed(
    profile, seed: int, taxonomy: TaxonomyLoader, weights=DEFAULT_WEIGHTS
) -> float:
    gen = SyntheticEventGenerator(rng=random.Random(seed))
    events = gen.generate("u1", profile, START, num_days=NUM_DAYS)
    result = run_data_quality_pipeline(events)
    windows = group_sessions_by_user_app_day(result.sessions)
    scores = []
    for sessions in windows.values():
        fv = build_feature_vector(sessions, taxonomy)
        category = taxonomy.lookup(fv.package_name).category
        scores.append(compute_heuristic_score(fv, category, weights=weights))
    return statistics.mean(scores) if scores else 0.0


class TestWeightsAreValid:
    def test_default_weights_sum_to_one(self):
        total = (
            DEFAULT_WEIGHTS.total_time_sec
            + DEFAULT_WEIGHTS.session_count
            + DEFAULT_WEIGHTS.sessions_under_30s_ratio
            + DEFAULT_WEIGHTS.interarrival_under_2min_ratio
            + DEFAULT_WEIGHTS.late_night_usage_time_ratio
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

def _fv(**overrides):
    """Hand-built FeatureVector so scoring rules can be tested without
    running the whole synthetic pipeline."""
    from attention_tracker.pipeline.features.feature_vector import FeatureVector

    base = dict(
        user_id="u1",
        package_name="com.example",
        total_time_sec=1800.0,
        session_count=10,
        avg_session_duration_sec=180.0,
        max_session_duration_sec=600.0,
        sessions_under_30s_ratio=0.2,
        interarrival_mean_sec=300.0,
        interarrival_under_2min_ratio=0.3,
        late_night_usage_pct=0.1,
        late_night_usage_time_ratio=0.1,
        hourly_usage_entropy=0.6,
        weekend_usage_ratio=0.0,
        productive_interruption_rate=0.1,
    )
    base.update(overrides)
    return FeatureVector(**base)


class TestCategoryMultiplier:
    """The app's category must change the score, not just PRODUCTIVE."""

    def test_same_behavior_scores_higher_on_addictive_than_productive(self):
        from attention_tracker.schema.app_metadata import AppCategory

        fv = _fv()
        addictive = compute_heuristic_score(fv, AppCategory.ADDICTIVE)
        productive = compute_heuristic_score(fv, AppCategory.PRODUCTIVE)
        assert addictive > productive

    def test_category_ordering_matches_design_intent(self):
        from attention_tracker.schema.app_metadata import AppCategory

        fv = _fv()
        score = lambda c: compute_heuristic_score(fv, c)  # noqa: E731
        assert (
            score(AppCategory.ADDICTIVE)
            > score(AppCategory.ENTERTAINMENT)
            > score(AppCategory.COMMUNICATION)
            > score(AppCategory.UTILITY)
            > score(AppCategory.PRODUCTIVE)
        )

    def test_unknown_is_not_scored_as_maximally_risky(self):
        from attention_tracker.schema.app_metadata import AppCategory

        fv = _fv()
        assert compute_heuristic_score(fv, AppCategory.UNKNOWN) < (
            compute_heuristic_score(fv, AppCategory.ADDICTIVE)
        )

    def test_score_stays_within_zero_to_ten(self):
        from attention_tracker.schema.app_metadata import AppCategory

        extreme = _fv(
            total_time_sec=1e9,
            session_count=10_000,
            sessions_under_30s_ratio=1.0,
            interarrival_under_2min_ratio=1.0,
            late_night_usage_time_ratio=1.0,
            weekend_usage_ratio=1.0,
            hourly_usage_entropy=0.0,
            productive_interruption_rate=1.0,
        )
        for category in AppCategory:
            assert 0.0 <= compute_heuristic_score(extreme, category) <= 10.0


class TestUndefinedFeaturesAreNotScoredAsMeasured:
    """A one-session window has no gap and no habit shape. Those
    features must be left out, not counted as 0 or as 'maximally
    concentrated'."""

    def test_none_interarrival_is_not_treated_as_zero(self):
        from attention_tracker.schema.app_metadata import AppCategory

        # Everything else equal, dropping a 0-valued term and
        # renormalizing must not LOWER the score of a window whose
        # other features are all high.
        high = dict(
            sessions_under_30s_ratio=0.9,
            late_night_usage_time_ratio=0.9,
            weekend_usage_ratio=1.0,
            productive_interruption_rate=0.9,
        )
        with_none = _fv(interarrival_under_2min_ratio=None, **high)
        with_zero = _fv(interarrival_under_2min_ratio=0.0, **high)
        assert compute_heuristic_score(
            with_none, AppCategory.ADDICTIVE
        ) > compute_heuristic_score(with_zero, AppCategory.ADDICTIVE)

    def test_single_session_entropy_does_not_change_score(self):
        from attention_tracker.schema.app_metadata import AppCategory

        # With one session, entropy is undefined. Two different
        # entropy values must produce the same score.
        a = _fv(session_count=1, interarrival_under_2min_ratio=None, hourly_usage_entropy=0.0)
        b = _fv(session_count=1, interarrival_under_2min_ratio=None, hourly_usage_entropy=0.9)
        assert compute_heuristic_score(a, AppCategory.ADDICTIVE) == pytest.approx(
            compute_heuristic_score(b, AppCategory.ADDICTIVE)
        )

    def test_multi_session_entropy_still_matters(self):
        from attention_tracker.schema.app_metadata import AppCategory

        low = _fv(hourly_usage_entropy=0.0)
        high = _fv(hourly_usage_entropy=0.9)
        assert compute_heuristic_score(
            low, AppCategory.ADDICTIVE
        ) > compute_heuristic_score(high, AppCategory.ADDICTIVE)