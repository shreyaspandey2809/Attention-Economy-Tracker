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
    single_session = fv.session_count < 2

    terms: list[tuple[float, float]] = [
        (
            weights.total_time_sec,
            _normalize_total_time_sec(fv.total_time_sec, bounds) * dampener,
        ),
        (
            weights.session_count,
            _normalize_session_count(fv.session_count, bounds),
        ),
        (weights.sessions_under_30s_ratio, fv.sessions_under_30s_ratio),
        (weights.late_night_usage_time_ratio, fv.late_night_usage_time_ratio),
        (weights.weekend_usage_ratio, fv.weekend_usage_ratio),
        (weights.productive_interruption_rate, fv.productive_interruption_rate),
    ]
    if fv.interarrival_under_2min_ratio is not None:
        terms.append(
            (weights.interarrival_under_2min_ratio, fv.interarrival_under_2min_ratio)
        )
    if not single_session:
        terms.append(
            (
                weights.hourly_usage_entropy,
                _normalize_hourly_usage_entropy_inverted(fv.hourly_usage_entropy)
                * dampener,
            )
        )

    weight_total = sum(w for w, _ in terms)
    weighted_sum = sum(w * v for w, v in terms) / weight_total

    multiplier = bounds.category_multipliers.get(app_category, 1.0)
    return weighted_sum * multiplier * 10.0