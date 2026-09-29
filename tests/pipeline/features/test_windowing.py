import pytest

from datetime import datetime, timedelta, timezone

from attention_tracker.schema.session import Session
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day

T0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


def make_session(user_id, package_name, start, duration_sec, session_id, tz_offset=0):
    return Session(
        user_id=user_id,
        package_name=package_name,
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
        tz_offset_minutes=tz_offset,
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


class TestWindowingUsesLocalDayNotUtcDay:
    """Windows must key on the session's LOCAL calendar
    day. A session stored at 20:30 UTC on Aug 10 is 02:00 IST on Aug
    11 for a UTC+5:30 user — the wrong day if keyed on UTC alone."""

    def test_ist_session_after_utc_midnight_boundary_keys_to_local_day(self):
        # 20:30 UTC, Aug 10 == 02:00 IST, Aug 11.
        session = make_session(
            "u1",
            "com.whatsapp",
            datetime(2026, 8, 10, 20, 30, tzinfo=timezone.utc),
            30.0,
            "s1",
            tz_offset=330,
        )
        groups = group_sessions_by_user_app_day([session])

        from datetime import date

        assert ("u1", "com.whatsapp", date(2026, 8, 11)) in groups
        assert ("u1", "com.whatsapp", date(2026, 8, 10)) not in groups

    def test_utc_offset_zero_is_unaffected(self):
        # UTC users (offset 0, the default) window by their UTC day
        # unchanged, since local day == UTC day for them.
        session = make_session(
            "u1", "com.whatsapp", T0, 30.0, "s1", tz_offset=0
        )
        groups = group_sessions_by_user_app_day([session])
        assert ("u1", "com.whatsapp", T0.date()) in groups

    def test_two_users_different_offsets_same_utc_instant_land_on_different_days(self):
        utc_instant = datetime(2026, 8, 10, 20, 30, tzinfo=timezone.utc)
        ist_session = make_session(
            "u1", "com.whatsapp", utc_instant, 30.0, "s1", tz_offset=330
        )
        utc_session = make_session(
            "u2", "com.whatsapp", utc_instant, 30.0, "s2", tz_offset=0
        )
        groups = group_sessions_by_user_app_day([ist_session, utc_session])

        from datetime import date

        assert ("u1", "com.whatsapp", date(2026, 8, 11)) in groups
        assert ("u2", "com.whatsapp", date(2026, 8, 10)) in groups

class TestWeeklyWindowing:
    """A week window sees Monday-Sunday together, so weekend share is a
    real ratio instead of a 0/1 day-type flag."""

    def test_sessions_in_same_iso_week_share_one_window(self):
        from datetime import date

        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        monday = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
        saturday = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        groups = group_sessions_by_user_app_week(
            [
                make_session("u1", "com.a", monday, 60.0, "s1"),
                make_session("u1", "com.a", saturday, 60.0, "s2"),
            ]
        )
        assert list(groups.keys()) == [("u1", "com.a", date(2026, 8, 3))]
        assert len(groups[("u1", "com.a", date(2026, 8, 3))]) == 2

    def test_next_monday_starts_a_new_window(self):
        from datetime import date

        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        sunday = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        next_monday = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        groups = group_sessions_by_user_app_week(
            [
                make_session("u1", "com.a", sunday, 60.0, "s1"),
                make_session("u1", "com.a", next_monday, 60.0, "s2"),
            ]
        )
        assert set(groups.keys()) == {
            ("u1", "com.a", date(2026, 8, 3)),
            ("u1", "com.a", date(2026, 8, 10)),
        }

    def test_week_uses_local_day_not_utc_day(self):
        from datetime import date

        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        # Sun 20:30 UTC == Mon 02:00 IST -> belongs to the NEXT week.
        utc_sunday_night = datetime(2026, 8, 9, 20, 30, tzinfo=timezone.utc)
        groups = group_sessions_by_user_app_week(
            [make_session("u1", "com.a", utc_sunday_night, 60.0, "s1", tz_offset=330)]
        )
        assert list(groups.keys()) == [("u1", "com.a", date(2026, 8, 10))]

    def test_weekend_ratio_over_a_week_is_a_real_fraction(self):
        from attention_tracker.pipeline.features.temporal import weekend_usage_ratio
        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        weekday = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)  # Wed
        weekend = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)  # Sat
        groups = group_sessions_by_user_app_week(
            [
                make_session("u1", "com.a", weekday, 300.0, "s1"),
                make_session("u1", "com.a", weekend, 100.0, "s2"),
            ]
        )
        (window,) = groups.values()
        assert weekend_usage_ratio(window) == pytest.approx(0.25)


class TestWeeklyWindowsReduceThinWindows:
    """End-to-end check on synthetic data: week windows must carry more
    signal than day windows, or the weekly grouping is pointless."""

    def _generate(self, seed=0, days=28):
        import random

        from attention_tracker.pipeline.quality.pipeline import (
            run_data_quality_pipeline,
        )
        from attention_tracker.synthetic.archetypes import BALANCED
        from attention_tracker.synthetic.generator import SyntheticEventGenerator

        gen = SyntheticEventGenerator(rng=random.Random(seed))
        events = gen.generate(
            "u1", BALANCED, datetime(2026, 8, 3, tzinfo=timezone.utc), days
        )
        return run_data_quality_pipeline(events).sessions

    def test_week_windows_have_fewer_single_session_windows_than_day_windows(self):
        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        sessions = self._generate()
        day = group_sessions_by_user_app_day(sessions)
        week = group_sessions_by_user_app_week(sessions)
        day_share = sum(len(v) == 1 for v in day.values()) / len(day)
        week_share = sum(len(v) == 1 for v in week.values()) / len(week)
        assert week_share < day_share

    def test_weekend_ratio_takes_many_values_over_weeks_but_two_over_days(self):
        from attention_tracker.pipeline.features.temporal import weekend_usage_ratio
        from attention_tracker.pipeline.windowing import (
            group_sessions_by_user_app_week,
        )

        sessions = self._generate()
        day_values = {
            round(weekend_usage_ratio(v), 3)
            for v in group_sessions_by_user_app_day(sessions).values()
        }
        week_values = {
            round(weekend_usage_ratio(v), 3)
            for v in group_sessions_by_user_app_week(sessions).values()
        }
        assert day_values <= {0.0, 1.0}
        assert len(week_values) > 2