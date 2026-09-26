from dataclasses import dataclass, field

from attention_tracker.schema.session import Session

MAX_PLAUSIBLE_SESSION_SEC: float = 4 * 60 * 60  # 4 hours


@dataclass
class OutlierCapResult:
    sessions: list[Session]
    capped_count: int = 0
    capped_session_ids: list[str] = field(default_factory=list)
    overlapping_session_ids: list[tuple[str, str]] = field(default_factory=list)


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
        overlapping_session_ids=_detect_overlaps(capped_sessions),
    )


def _detect_overlaps(sessions: list[Session]) -> list[tuple[str, str]]:
    by_user: dict[str, list[Session]] = {}
    for s in sessions:
        by_user.setdefault(s.user_id, []).append(s)

    overlaps: list[tuple[str, str]] = []
    for user_sessions in by_user.values():
        ordered = sorted(user_sessions, key=lambda s: s.start_time)
        # (end_time, session_id) of the session with the latest end_time
        # among everything swept so far.
        running_latest_end = ordered[0].end_time
        running_latest_end_id = ordered[0].session_id
        for current in ordered[1:]:
            if current.start_time < running_latest_end:
                overlaps.append((running_latest_end_id, current.session_id))
            if current.end_time > running_latest_end:
                running_latest_end = current.end_time
                running_latest_end_id = current.session_id
    return overlaps


def _seconds_to_timedelta(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)