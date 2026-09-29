from collections import defaultdict
from datetime import date, timedelta

from attention_tracker.schema.session import Session


def group_sessions_by_user_app_day(sessions: list[Session],) -> dict[tuple[str, str, date], list[Session]]:
    groups: dict[tuple[str, str, date], list[Session]] = defaultdict(list)
    for session in sessions:
        key = (session.user_id, session.package_name, session.local_start_time.date())
        groups[key].append(session)

    for group in groups.values():
        group.sort(key=lambda s: s.local_start_time)

    return dict(groups)


def group_sessions_by_user_app_week(
    sessions: list[Session],
) -> dict[tuple[str, str, date], list[Session]]:
    groups: dict[tuple[str, str, date], list[Session]] = defaultdict(list)
    for session in sessions:
        local_day = session.local_start_time.date()
        week_start = local_day - timedelta(days=local_day.weekday())
        groups[(session.user_id, session.package_name, week_start)].append(session)

    for group in groups.values():
        group.sort(key=lambda s: s.local_start_time)

    return dict(groups)