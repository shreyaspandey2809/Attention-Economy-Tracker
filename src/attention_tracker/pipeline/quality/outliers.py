from dataclasses import dataclass, field

from attention_tracker.schema.session import Session

MAX_PLAUSIBLE_SESSION_SEC: float = 4 * 60 * 60  # 4 hours


@dataclass
class OutlierCapResult:
    sessions: list[Session]
    capped_count: int = 0
    capped_session_ids: list[str] = field(default_factory=list)


def cap_session_outliers(
    sessions: list[Session],
    max_plausible_sec: float = MAX_PLAUSIBLE_SESSION_SEC,
) -> OutlierCapResult:
    capped_sessions: list[Session] = []
    capped_ids: list[str] = []

    for session in sessions:
        if session.duration_sec <= max_plausible_sec:
            capped_sessions.append(session)
            continue

        capped_end_time = session.start_time + _seconds_to_timedelta(
            max_plausible_sec
        )
        capped_sessions.append(
            session.model_copy(
                update={
                    "end_time": capped_end_time,
                    "duration_sec": max_plausible_sec,
                }
            )
        )
        capped_ids.append(session.session_id)

    return OutlierCapResult(
        sessions=capped_sessions,
        capped_count=len(capped_ids),
        capped_session_ids=capped_ids,
    )


def _seconds_to_timedelta(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)