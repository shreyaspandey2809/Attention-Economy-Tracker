from datetime import datetime, timedelta, timezone

from attention_tracker.schema.session import Session
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day

T0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


def make_session(user_id, package_name, start, duration_sec, session_id):
    return Session(
        user_id=user_id,
        package_name=package_name,
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
    )


class TestGroupSessionsByUserAppDay:
    def test_groups_by_user_app_and_calendar_day(self):
        sessions = [
            make_session("u1", "com.whatsapp", T0, 30.0, "s1"),
            make_session("u1", "com.whatsapp", T0 + timedelta(minutes=5), 30.0, "s2"),
            make_session("u1", "com.instagram.android", T0, 60.0, "s3"),
            make_session("u2", "com.whatsapp", T0, 30.0, "s4"),
        ]
        groups = group_sessions_by_user_app_day(sessions)

        assert len(groups) == 3
        key_u1_whatsapp = ("u1", "com.whatsapp", T0.date())
        assert len(groups[key_u1_whatsapp]) == 2

    def test_different_calendar_days_are_separate_groups(self):
        sessions = [
            make_session("u1", "com.whatsapp", T0, 30.0, "s1"),
            make_session(
                "u1", "com.whatsapp", T0 + timedelta(days=1), 30.0, "s2"
            ),
        ]
        groups = group_sessions_by_user_app_day(sessions)
        assert len(groups) == 2

    def test_groups_are_sorted_by_start_time(self):
        sessions = [
            make_session("u1", "com.whatsapp", T0 + timedelta(minutes=10), 30.0, "s2"),
            make_session("u1", "com.whatsapp", T0, 30.0, "s1"),
        ]
        groups = group_sessions_by_user_app_day(sessions)
        group = groups[("u1", "com.whatsapp", T0.date())]
        assert group[0].session_id == "s1"
        assert group[1].session_id == "s2"

    def test_empty_input_returns_empty_dict(self):
        assert group_sessions_by_user_app_day([]) == {}