from attention_tracker.schema.session import Session
def total_time_sec(sessions: list[Session]) -> float:
    """Sum of all session durations in the window."""
    if not sessions:
        raise ValueError("total_time_sec requires at least one session")
    return sum(s.duration_sec for s in sessions)
def session_count(sessions: list[Session]) -> int:
    """Number of sessions in the window."""
    if not sessions:
        raise ValueError("session_count requires at least one session")
    return len(sessions)
def avg_session_duration_sec(sessions: list[Session]) -> float:
    """Mean session duration in the window."""
    if not sessions:
        raise ValueError("avg_session_duration_sec requires at least one session")
    return total_time_sec(sessions) / len(sessions)
def max_session_duration_sec(sessions: list[Session]) -> float:
    """Longest single session in the window — flags binge-length
    outlier sessions that a mean alone would smooth over."""
    if not sessions:
        raise ValueError("max_session_duration_sec requires at least one session")
    return max(s.duration_sec for s in sessions)