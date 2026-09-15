from dataclasses import dataclass

from attention_tracker.pipeline.features.compulsiveness import (
    interarrival_mean_sec,
    interarrival_under_2min_ratio,
    sessions_under_30s_ratio,
)
from attention_tracker.pipeline.features.temporal import (
    hourly_usage_entropy,
    late_night_usage_pct,
    late_night_usage_time_ratio,
    weekend_usage_ratio,
)
from attention_tracker.pipeline.features.transitions import (
    productive_interruption_rate,
)
from attention_tracker.pipeline.features.volume import (
    avg_session_duration_sec,
    max_session_duration_sec,
    session_count,
    total_time_sec,
)
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader


@dataclass(frozen=True)
class FeatureVector:
    user_id: str
    package_name: str

    # Volume
    total_time_sec: float
    session_count: int
    avg_session_duration_sec: float
    max_session_duration_sec: float

    # Compulsiveness
    sessions_under_30s_ratio: float
    interarrival_mean_sec: float | None
    interarrival_under_2min_ratio: float | None

    # Temporal
    late_night_usage_pct: float
    late_night_usage_time_ratio: float
    hourly_usage_entropy: float
    weekend_usage_ratio: float

    # Transitions
    productive_interruption_rate: float


def build_feature_vector(
    sessions: list[Session],
    taxonomy: TaxonomyLoader,
) -> FeatureVector:
    if not sessions:
        raise ValueError("build_feature_vector requires at least one session")

    user_id = sessions[0].user_id
    package_name = sessions[0].package_name
    has_multiple = len(sessions) >= 2

    return FeatureVector(
        user_id=user_id,
        package_name=package_name,
        total_time_sec=total_time_sec(sessions),
        session_count=session_count(sessions),
        avg_session_duration_sec=avg_session_duration_sec(sessions),
        max_session_duration_sec=max_session_duration_sec(sessions),
        sessions_under_30s_ratio=sessions_under_30s_ratio(sessions),
        interarrival_mean_sec=(
            interarrival_mean_sec(sessions) if has_multiple else None
        ),
        interarrival_under_2min_ratio=(
            interarrival_under_2min_ratio(sessions) if has_multiple else None
        ),
        late_night_usage_pct=late_night_usage_pct(sessions),
        late_night_usage_time_ratio=late_night_usage_time_ratio(sessions),
        hourly_usage_entropy=hourly_usage_entropy(sessions),
        weekend_usage_ratio=weekend_usage_ratio(sessions),
        productive_interruption_rate=productive_interruption_rate(
            sessions, taxonomy
        ),
    )