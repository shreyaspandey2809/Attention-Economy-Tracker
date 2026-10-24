from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.scoring.config import (
    DEFAULT_BOUNDS,
    DEFAULT_DISTRACTION_WEIGHTS,
    DistractionWeights,
    NormalizationBounds,
)
from attention_tracker.scoring.heuristic import (
    _clamp01,
    _normalize_session_count,
    _normalize_total_time_sec,
)


def compute_distraction_score(
    fv: FeatureVector,
    app_category: AppCategory,
    weights: DistractionWeights = DEFAULT_DISTRACTION_WEIGHTS,
    bounds: NormalizationBounds = DEFAULT_BOUNDS,
) -> float:
    single_session = fv.session_count < 2

    terms: list[tuple[float, float]] = [
        (weights.sessions_under_30s_ratio, fv.sessions_under_30s_ratio),
        (weights.productive_interruption_rate, fv.productive_interruption_rate),
        (weights.session_count, _normalize_session_count(fv.session_count, bounds)),
        (weights.total_time_sec, _normalize_total_time_sec(fv.total_time_sec, bounds)),
    ]
    if fv.interarrival_under_2min_ratio is not None:
        terms.append(
            (weights.interarrival_under_2min_ratio, fv.interarrival_under_2min_ratio)
        )
    if not single_session:
        terms.append((weights.hourly_usage_entropy, _clamp01(fv.hourly_usage_entropy)))

    weight_total = sum(w for w, _ in terms)
    weighted_sum = sum(w * v for w, v in terms) / weight_total

    multiplier = bounds.distraction_category_multipliers.get(app_category, 1.0)
    return weighted_sum * multiplier * 10.0