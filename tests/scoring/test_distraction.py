import pytest

from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.scoring.config import (
    DEFAULT_DISTRACTION_WEIGHTS,
    DistractionWeights,
)
from attention_tracker.scoring.distraction import compute_distraction_score
from attention_tracker.scoring.heuristic import compute_heuristic_score


def _fv(**overrides) -> FeatureVector:
    defaults = dict(
        user_id="u1",
        package_name="com.example.app",
        total_time_sec=600.0,
        session_count=10,
        avg_session_duration_sec=60.0,
        max_session_duration_sec=200.0,
        sessions_under_30s_ratio=0.2,
        interarrival_mean_sec=300.0,
        interarrival_under_2min_ratio=0.2,
        late_night_usage_pct=0.0,
        late_night_usage_time_ratio=0.0,
        hourly_usage_entropy=0.5,
        weekend_usage_ratio=0.0,
        productive_interruption_rate=0.0,
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


def test_default_weights_sum_to_one():
    w = DEFAULT_DISTRACTION_WEIGHTS
    total = (
        w.sessions_under_30s_ratio
        + w.interarrival_under_2min_ratio
        + w.productive_interruption_rate
        + w.session_count
        + w.hourly_usage_entropy
        + w.total_time_sec
    )
    assert total == pytest.approx(1.0)


def test_weights_that_do_not_sum_to_one_are_rejected():
    with pytest.raises(ValueError):
        DistractionWeights(sessions_under_30s_ratio=0.9)


def test_score_stays_within_0_to_10():
    worst = _fv(
        total_time_sec=1e6,
        session_count=500,
        sessions_under_30s_ratio=1.0,
        interarrival_under_2min_ratio=1.0,
        hourly_usage_entropy=1.0,
        productive_interruption_rate=1.0,
    )
    best = _fv(
        total_time_sec=0.0,
        session_count=2,
        sessions_under_30s_ratio=0.0,
        interarrival_under_2min_ratio=0.0,
        hourly_usage_entropy=0.0,
        productive_interruption_rate=0.0,
    )
    assert 0.0 <= compute_distraction_score(best, AppCategory.ADDICTIVE) <= 10.0
    assert compute_distraction_score(worst, AppCategory.ADDICTIVE) == pytest.approx(10.0)


def test_productive_interruptions_raise_distraction():
    calm = compute_distraction_score(_fv(), AppCategory.COMMUNICATION)
    pulled = compute_distraction_score(
        _fv(productive_interruption_rate=0.8), AppCategory.COMMUNICATION
    )
    assert pulled > calm


def test_late_night_and_weekend_do_not_change_distraction_but_do_change_addiction():
    base = _fv()
    night = _fv(
        late_night_usage_pct=0.9,
        late_night_usage_time_ratio=0.9,
        weekend_usage_ratio=0.9,
    )
    assert compute_distraction_score(night, AppCategory.ADDICTIVE) == pytest.approx(
        compute_distraction_score(base, AppCategory.ADDICTIVE)
    )
    assert compute_heuristic_score(night, AppCategory.ADDICTIVE) > compute_heuristic_score(
        base, AppCategory.ADDICTIVE
    )


def test_scattered_usage_is_more_distracting_but_less_addictive_than_concentrated():
    scattered = _fv(hourly_usage_entropy=0.95)
    focused = _fv(hourly_usage_entropy=0.1)
    assert compute_distraction_score(scattered, AppCategory.ADDICTIVE) > compute_distraction_score(
        focused, AppCategory.ADDICTIVE
    )
    assert compute_heuristic_score(scattered, AppCategory.ADDICTIVE) < compute_heuristic_score(
        focused, AppCategory.ADDICTIVE
    )


def test_productive_app_scores_lower_than_communication_app():
    fv = _fv(sessions_under_30s_ratio=0.8, productive_interruption_rate=0.5)
    assert compute_distraction_score(fv, AppCategory.PRODUCTIVE) < compute_distraction_score(
        fv, AppCategory.COMMUNICATION
    )


def test_single_session_window_skips_entropy_and_missing_interarrival():
    fv = _fv(
        session_count=1,
        interarrival_mean_sec=None,
        interarrival_under_2min_ratio=None,
        hourly_usage_entropy=0.0,
    )
    score = compute_distraction_score(fv, AppCategory.ADDICTIVE)
    assert 0.0 <= score <= 10.0