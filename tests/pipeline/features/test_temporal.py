from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.pipeline.features.temporal import (
    hourly_usage_entropy,
    late_night_usage_pct,
    weekend_usage_ratio,
)
from attention_tracker.schema.session import Session


def make_session(start, duration_sec=60.0, session_id="s1"):
    return Session(
        user_id="u1",
        package_name="com.whatsapp",
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
    )


class TestLateNightUsagePct:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least one session"):
            late_night_usage_pct([])

    def test_all_late_night_sessions(self):
        # Hours 23, 0, 1, 2, 3 — matching the generator's own
        # late-night window exactly.
        sessions = [
            make_session(datetime(2026, 8, 10, 23, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc), session_id="s2"),
            make_session(datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc), session_id="s3"),
        ]
        assert late_night_usage_pct(sessions) == 1.0

    def test_no_late_night_sessions(self):
        sessions = [
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc), session_id="s2"),
        ]
        assert late_night_usage_pct(sessions) == 0.0

    def test_boundary_hours_4_and_22_are_not_late_night(self):
        # 4am and 10pm are just outside the 23:00-04:00 window —
        # this pins the exact boundary the generator itself uses
        # (hours 23,0,1,2,3 only; NOT hour 4).
        sessions = [
            make_session(datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc), session_id="s2"),
        ]
        assert late_night_usage_pct(sessions) == 0.0

    def test_mixed_sessions_gives_correct_ratio(self):
        sessions = [
            make_session(datetime(2026, 8, 10, 23, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), session_id="s2"),
            make_session(datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc), session_id="s3"),
            make_session(datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc), session_id="s4"),
        ]
        assert late_night_usage_pct(sessions) == 0.5


class TestHourlyUsageEntropy:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least one session"):
            hourly_usage_entropy([])

    def test_single_session_is_zero_entropy(self):
        sessions = [make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc))]
        assert hourly_usage_entropy(sessions) == 0.0

    def test_all_sessions_same_hour_is_zero_entropy(self):
        sessions = [
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc), session_id="s2"),
            make_session(datetime(2026, 8, 11, 9, 15, tzinfo=timezone.utc), session_id="s3"),
        ]
        assert hourly_usage_entropy(sessions) == 0.0

    def test_uniform_across_all_24_hours_is_near_one(self):
        sessions = [
            make_session(
                datetime(2026, 8, 10, hour, 0, tzinfo=timezone.utc),
                session_id=f"s{hour}",
            )
            for hour in range(24)
        ]
        assert hourly_usage_entropy(sessions) == pytest.approx(1.0, abs=1e-9)

    def test_two_hours_gives_intermediate_entropy(self):
        sessions = [
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc), session_id="s2"),
        ]
        entropy = hourly_usage_entropy(sessions)
        assert 0.0 < entropy < 1.0

    def test_result_is_always_between_0_and_1(self):
        sessions = [
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), session_id="s1"),
            make_session(datetime(2026, 8, 10, 9, 5, tzinfo=timezone.utc), session_id="s2"),
            make_session(datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc), session_id="s3"),
            make_session(datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc), session_id="s4"),
        ]
        entropy = hourly_usage_entropy(sessions)
        assert 0.0 <= entropy <= 1.0


class TestWeekendUsageRatio:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least one session"):
            weekend_usage_ratio([])

    def test_all_weekday_sessions(self):
        # Aug 10, 2026 is a Monday.
        sessions = [
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), 600.0, "s1"),
        ]
        assert weekend_usage_ratio(sessions) == 0.0

    def test_all_weekend_sessions(self):
        # Aug 8, 2026 is a Saturday; Aug 9 is a Sunday.
        sessions = [
            make_session(datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc), 600.0, "s1"),
            make_session(datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc), 600.0, "s2"),
        ]
        assert weekend_usage_ratio(sessions) == 1.0

    def test_weighted_by_duration_not_count(self):
        # Saturday: 1 long session (900s). Monday: 3 short sessions
        # (100s each = 300s). Weekend ratio should reflect TIME
        # (900 / 1200 = 0.75), not session count (1/4 = 0.25).
        sessions = [
            make_session(datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc), 900.0, "s1"),
            make_session(datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc), 100.0, "s2"),
            make_session(datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc), 100.0, "s3"),
            make_session(datetime(2026, 8, 10, 11, 0, tzinfo=timezone.utc), 100.0, "s4"),
        ]
        assert weekend_usage_ratio(sessions) == pytest.approx(0.75)