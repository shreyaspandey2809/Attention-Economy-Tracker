from dataclasses import dataclass, field

from attention_tracker.pipeline.quality.dedup import DedupResult, dedupe_events
from attention_tracker.pipeline.quality.outliers import (
    OutlierCapResult,
    cap_session_outliers,
)
from attention_tracker.pipeline.session_builder import SessionBuilder, SessionBuildResult
from attention_tracker.schema.raw_event import RawEvent
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader


@dataclass
class DataQualityPipelineResult:

    sessions: list[Session]
    dedup_result: DedupResult
    build_result: SessionBuildResult
    outlier_result: OutlierCapResult
    # Events for system surfaces (launcher, system UI, keyboard,
    # dialer, installer) removed before session building. 0 when no
    # taxonomy is passed.
    ignored_event_count: int = 0


def run_data_quality_pipeline(
    events: list[RawEvent],
    max_plausible_session_sec: float | None = None,
    taxonomy: TaxonomyLoader | None = None,
) -> DataQualityPipelineResult:
    dedup_result = dedupe_events(events)

    events_for_build = dedup_result.events
    ignored_event_count = 0
    if taxonomy is not None:
        kept = [e for e in events_for_build if not taxonomy.is_ignored(e.package_name)]
        ignored_event_count = len(events_for_build) - len(kept)
        events_for_build = kept

    build_result = SessionBuilder().build(events_for_build)

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
        ignored_event_count=ignored_event_count,
    )