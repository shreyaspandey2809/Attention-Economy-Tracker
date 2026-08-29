from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.schema.session import Session
from attention_tracker.pipeline.features.compulsiveness import (
    interarrival_mean_sec,
    interarrival_under_2min_ratio,
    sessions_under_30s_ratio,
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


class TestInterarrivalMeanSec:
    def test_computes_gap_between_two_sessions(self):
        # s1: T0 to T0+30s. s2 starts 90s after s1 ends.
        s1 = make_session(T0, 30.0, "s1")
        s2_start = s1.end_time + timedelta(seconds=90)
        s2 = make_session(s2_start, 30.0, "s2")

        assert interarrival_mean_sec([s1, s2]) == 90.0

    def test_averages_multiple_gaps(self):
        s1 = make_session(T0, 30.0, "s1")
        s2 = make_session(s1.end_time + timedelta(seconds=60), 30.0, "s2")
        s3 = make_session(s2.end_time + timedelta(seconds=120), 30.0, "s3")

        # gaps: 60s, 120s -> mean 90s
        assert interarrival_mean_sec([s1, s2, s3]) == 90.0

    def test_single_session_raises(self):
        with pytest.raises(ValueError, match="at least 2 sessions"):
            interarrival_mean_sec([make_session(T0, 30.0, "s1")])

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            interarrival_mean_sec([])

    def test_out_of_order_sessions_raise(self):
        s1 = make_session(T0, 30.0, "s1")
        s2 = make_session(T0 - timedelta(minutes=5), 30.0, "s2")  # earlier!
        with pytest.raises(ValueError, match="pre-sorted"):
            interarrival_mean_sec([s1, s2])


class TestSessionsUnder30sRatio:
    def test_computes_ratio_of_short_sessions(self):
        sessions = [
            make_session(T0, 10.0, "s1"),   # short
            make_session(T0, 45.0, "s2"),   # not short
            make_session(T0, 20.0, "s3"),   # short
            make_session(T0, 100.0, "s4"),  # not short
        ]
        assert sessions_under_30s_ratio(sessions) == 0.5

    def test_all_short_sessions(self):
        sessions = [make_session(T0, 5.0, "s1"), make_session(T0, 10.0, "s2")]
        assert sessions_under_30s_ratio(sessions) == 1.0

    def test_no_short_sessions(self):
        sessions = [make_session(T0, 60.0, "s1"), make_session(T0, 90.0, "s2")]
        assert sessions_under_30s_ratio(sessions) == 0.0

    def test_boundary_exactly_30s_is_not_short(self):
        sessions = [make_session(T0, 30.0, "s1")]
        assert sessions_under_30s_ratio(sessions) == 0.0

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            sessions_under_30s_ratio([])


class TestInterarrivalUnder2MinRatio:
    def test_computes_ratio_of_quick_returns(self):
        s1 = make_session(T0, 30.0, "s1")
        s2 = make_session(s1.end_time + timedelta(seconds=30), 30.0, "s2")  # quick
        s3 = make_session(s2.end_time + timedelta(minutes=10), 30.0, "s3")  # slow
        s4 = make_session(s3.end_time + timedelta(seconds=45), 30.0, "s4")  # quick

        # gaps: 30s (quick), 600s (slow), 45s (quick) -> 2/3 quick
        assert interarrival_under_2min_ratio([s1, s2, s3, s4]) == pytest.approx(2 / 3)

    def test_single_session_raises(self):
        with pytest.raises(ValueError):
            interarrival_under_2min_ratio([make_session(T0, 30.0, "s1")])

    def test_less_sensitive_to_outlier_than_mean(self):
        """A single very long gap pulls the mean up but shouldn't
        dominate the ratio the same way."""
        s1 = make_session(T0, 30.0, "s1")
        s2 = make_session(s1.end_time + timedelta(seconds=10), 30.0, "s2")
        s3 = make_session(s2.end_time + timedelta(seconds=10), 30.0, "s3")
        s4 = make_session(
            s3.end_time + timedelta(hours=5), 30.0, "s4"
        )  # one huge outlier gap

        ratio = interarrival_under_2min_ratio([s1, s2, s3, s4])
        mean = interarrival_mean_sec([s1, s2, s3, s4])

        # 2 of 3 gaps are quick, despite the outlier dragging the mean
        # up to nearly 2 hours.
        assert ratio == pytest.approx(2 / 3)
        assert mean > 3000  # mean is dominated by the outlier