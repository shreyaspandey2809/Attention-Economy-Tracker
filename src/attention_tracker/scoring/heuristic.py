from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.scoring.config import (
    DEFAULT_BOUNDS,
    DEFAULT_WEIGHTS,
    HeuristicWeights,
    NormalizationBounds,
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize_total_time_sec(value: float, bounds: NormalizationBounds) -> float:
    return _clamp01(value / bounds.total_time_sec_cap)


def _normalize_session_count(value: int, bounds: NormalizationBounds) -> float:
    return _clamp01(value / bounds.session_count_cap)


def _normalize_hourly_usage_entropy_inverted(value: float) -> float:
    return _clamp01(1.0 - value)


def compute_heuristic_score(
    fv: FeatureVector,
    app_category: AppCategory,
    weights: HeuristicWeights = DEFAULT_WEIGHTS,
    bounds: NormalizationBounds = DEFAULT_BOUNDS,
) -> float:
    is_productive = app_category == AppCategory.PRODUCTIVE
    dampener = bounds.productive_app_dampener if is_productive else 1.0

    normalized_total_time = _normalize_total_time_sec(fv.total_time_sec, bounds) * dampener
    normalized_session_count = _normalize_session_count(fv.session_count, bounds)
    normalized_entropy = (
        _normalize_hourly_usage_entropy_inverted(fv.hourly_usage_entropy) * dampener
    )

    weighted_sum = (
        weights.total_time_sec * normalized_total_time
        + weights.session_count * normalized_session_count
        + weights.sessions_under_30s_ratio * fv.sessions_under_30s_ratio
        + weights.interarrival_under_2min_ratio
        * (fv.interarrival_under_2min_ratio or 0.0)
        + weights.late_night_usage_time_ratio * fv.late_night_usage_time_ratio
        + weights.weekend_usage_ratio * fv.weekend_usage_ratio
        + weights.hourly_usage_entropy * normalized_entropy
        + weights.productive_interruption_rate * fv.productive_interruption_rate
    )
    return weighted_sum * 10.0