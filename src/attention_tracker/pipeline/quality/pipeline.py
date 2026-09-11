from dataclasses import dataclass, field

from attention_tracker.pipeline.quality.dedup import DedupResult, dedupe_events
from attention_tracker.pipeline.quality.outliers import (
    OutlierCapResult,
    cap_session_outliers,
)
from attention_tracker.pipeline.session_builder import SessionBuilder, SessionBuildResult
from attention_tracker.schema.raw_event import RawEvent
from attention_tracker.schema.session import Session


@dataclass
class DataQualityPipelineResult:

    sessions: list[Session]
    dedup_result: DedupResult
    build_result: SessionBuildResult
    outlier_result: OutlierCapResult


def run_data_quality_pipeline(
    events: list[RawEvent],
    max_plausible_session_sec: float | None = None,
) -> DataQualityPipelineResult:
    dedup_result = dedupe_events(events)

    build_result = SessionBuilder().build(dedup_result.events)

    if max_plausible_session_sec is not None:
        outlier_result = cap_session_outliers(
            build_result.sessions, max_plausible_sec=max_plausible_session_sec
        )
    else:
        outlier_result = cap_session_outliers(build_result.sessions)

    return DataQualityPipelineResult(
        sessions=outlier_result.sessions,
        dedup_result=dedup_result,
        build_result=build_result,
        outlier_result=outlier_result,
    )