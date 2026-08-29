from collections import defaultdict
from datetime import date

from attention_tracker.schema.session import Session


def group_sessions_by_user_app_day(sessions: list[Session],) -> dict[tuple[str, str, date], list[Session]]:
    groups: dict[tuple[str, str, date], list[Session]] = defaultdict(list)
    for session in sessions:
        key = (session.user_id, session.package_name, session.start_time.date())
        groups[key].append(session)

    for group in groups.values():
        group.sort(key=lambda s: s.start_time)

    return dict(groups)