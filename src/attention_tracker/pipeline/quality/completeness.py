from dataclasses import dataclass
from datetime import date
from attention_tracker.schema.session import Session
DEFAULT_MAX_GAP_HOURS: float = 6.0

@dataclass(frozen=True)
class CompletenessResult:
    user_id: str
    day: date
    is_complete: bool
    max_gap_hours: float
    reason: str


def assess_day_completeness(
    all_sessions_for_user_day: list[Session],
    max_gap_hours: float = DEFAULT_MAX_GAP_HOURS,
) -> CompletenessResult:
    if not all_sessions_for_user_day:
        return CompletenessResult(
            user_id="unknown",
            day=date.today(),
            is_complete=False,
            max_gap_hours=24.0,
            reason="no sessions recorded for this user on this day",
        )

    user_id = all_sessions_for_user_day[0].user_id
    day = all_sessions_for_user_day[0].start_time.date()

    sessions_sorted = sorted(all_sessions_for_user_day, key=lambda s: s.start_time)

    gaps_hours = [
        (sessions_sorted[i].start_time - sessions_sorted[i - 1].end_time).total_seconds()
        / 3600.0
        for i in range(1, len(sessions_sorted))
    ]

    max_gap = max(gaps_hours) if gaps_hours else 0.0
    is_complete = max_gap <= max_gap_hours

    reason = (
        f"largest session-free gap ({max_gap:.1f}h) is within the "
        f"{max_gap_hours:.1f}h threshold"
        if is_complete
        else (
            f"largest session-free gap ({max_gap:.1f}h) exceeds the "
            f"{max_gap_hours:.1f}h threshold — this may indicate a sync "
            f"gap OR genuine non-use; this heuristic cannot tell the "
            f"difference (see module docstring)"
        )
    )

    return CompletenessResult(
        user_id=user_id,
        day=day,
        is_complete=is_complete,
        max_gap_hours=max_gap,
        reason=reason,
    )