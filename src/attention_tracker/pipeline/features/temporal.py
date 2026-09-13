import math
from collections import Counter

from attention_tracker.schema.session import Session

LATE_NIGHT_HOURS: frozenset[int] = frozenset({23, 0, 1, 2, 3})
WEEKEND_ISO_WEEKDAYS: frozenset[int] = frozenset({6, 7})  # Sat=6, Sun=7


def late_night_usage_pct(sessions: list[Session]) -> float:
    if not sessions:
        raise ValueError("late_night_usage_pct requires at least one session")

    late_night_count = sum(
        1 for s in sessions if s.start_time.hour in LATE_NIGHT_HOURS
    )
    return late_night_count / len(sessions)


def hourly_usage_entropy(sessions: list[Session]) -> float:
    if not sessions:
        raise ValueError("hourly_usage_entropy requires at least one session")

    hour_counts = Counter(s.start_time.hour for s in sessions)
    total = len(sessions)

    if len(hour_counts) <= 1:
        return 0.0

    entropy = -sum(
        (count / total) * math.log2(count / total)
        for count in hour_counts.values()
    )
    max_entropy = math.log2(24)
    return entropy / max_entropy


def weekend_usage_ratio(sessions: list[Session]) -> float:
    if not sessions:
        raise ValueError("weekend_usage_ratio requires at least one session")

    total = sum(s.duration_sec for s in sessions)
    if total == 0:
        return 0.0

    weekend_time = sum(
        s.duration_sec
        for s in sessions
        if s.start_time.isoweekday() in WEEKEND_ISO_WEEKDAYS
    )
    return weekend_time / total