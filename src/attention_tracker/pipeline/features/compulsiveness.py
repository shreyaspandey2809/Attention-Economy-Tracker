from attention_tracker.schema.session import Session
def _assert_sorted_by_start(sessions: list[Session]) -> None:
    for i in range(1, len(sessions)):
        if sessions[i].start_time < sessions[i - 1].start_time:
            raise ValueError(
                "sessions must be pre-sorted by start_time; got an "
                f"out-of-order pair at index {i - 1}/{i}"
            )
def interarrival_mean_sec(sessions: list[Session]) -> float:
    if len(sessions) < 2:
        raise ValueError(
            "interarrival_mean_sec requires at least 2 sessions to measure a gap"
        )
    _assert_sorted_by_start(sessions)

    gaps = [
        (sessions[i].start_time - sessions[i - 1].end_time).total_seconds()
        for i in range(1, len(sessions))
    ]
    return sum(gaps) / len(gaps)


def sessions_under_30s_ratio(sessions: list[Session]) -> float:
    if not sessions:
        raise ValueError("sessions_under_30s_ratio requires at least one session")
    short = sum(1 for s in sessions if s.duration_sec < 30.0)
    return short / len(sessions)


def interarrival_under_2min_ratio(sessions: list[Session]) -> float:
    if len(sessions) < 2:
        raise ValueError(
            "interarrival_under_2min_ratio requires at least 2 sessions"
        )
    _assert_sorted_by_start(sessions)

    gaps = [
        (sessions[i].start_time - sessions[i - 1].end_time).total_seconds()
        for i in range(1, len(sessions))
    ]
    quick = sum(1 for g in gaps if g < 120.0)
    return quick / len(gaps)