from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.schema.session import Session
from attention_tracker.pipeline.features.volume import (
    avg_session_duration_sec,
    max_session_duration_sec,
    session_count,
    total_time_sec,
)

T0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


def make_session(start, duration_sec, session_id):
    return Session(
        user_id="u1",
        package_name="com.whatsapp",
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
    )


class TestTotalTimeSec:
    def test_sums_durations(self):
        sessions = [
            make_session(T0, 30.0, "s1"),
            make_session(T0 + timedelta(minutes=5), 90.0, "s2"),
            make_session(T0 + timedelta(minutes=10), 45.0, "s3"),
        ]
        assert total_time_sec(sessions) == 165.0

    def test_single_session(self):
        assert total_time_sec([make_session(T0, 30.0, "s1")]) == 30.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="at least one session"):
            total_time_sec([])


class TestSessionCount:
    def test_counts_sessions(self):
        sessions = [make_session(T0, 30.0, "s1"), make_session(T0, 30.0, "s2")]
        assert session_count(sessions) == 2

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            session_count([])


class TestAvgSessionDurationSec:
    def test_computes_mean(self):
        sessions = [
            make_session(T0, 30.0, "s1"),
            make_session(T0, 90.0, "s2"),
        ]
        assert avg_session_duration_sec(sessions) == 60.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            avg_session_duration_sec([])


class TestMaxSessionDurationSec:
    def test_finds_longest_session(self):
        sessions = [
            make_session(T0, 30.0, "s1"),
            make_session(T0, 500.0, "s2"),
            make_session(T0, 45.0, "s3"),
        ]
        assert max_session_duration_sec(sessions) == 500.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            max_session_duration_sec([])