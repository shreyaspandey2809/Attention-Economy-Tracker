from datetime import datetime, timedelta, timezone

from attention_tracker.pipeline.quality.completeness import (
    DEFAULT_MAX_GAP_HOURS,
    assess_day_completeness,
)
from attention_tracker.schema.session import Session

DAY_START = datetime(2026, 8, 10, 0, 0, 0, tzinfo=timezone.utc)


def make_session(start, duration_sec, session_id, package="com.whatsapp"):
    return Session(
        user_id="u1",
        package_name=package,
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
    )


class TestEmptyInput:
    def test_empty_list_is_flagged_incomplete(self):
        result = assess_day_completeness([])
        assert result.is_complete is False
        assert "no sessions recorded" in result.reason


class TestGapDetection:
    def test_sessions_with_small_gaps_are_complete(self):
        sessions = [
            make_session(DAY_START + timedelta(hours=9), 600.0, "s1"),
            make_session(DAY_START + timedelta(hours=11), 600.0, "s2"),
            make_session(DAY_START + timedelta(hours=14), 600.0, "s3"),
        ]
        result = assess_day_completeness(sessions)
        assert result.is_complete is True

    def test_large_gap_is_flagged_incomplete(self):
        sessions = [
            make_session(DAY_START + timedelta(hours=1), 600.0, "s1"),
            # 10-hour gap between s1's end and s2's start — well above
            # the default 6-hour threshold.
            make_session(DAY_START + timedelta(hours=11, minutes=10), 600.0, "s2"),
        ]
        result = assess_day_completeness(sessions)
        assert result.is_complete is False
        assert result.max_gap_hours > DEFAULT_MAX_GAP_HOURS

    def test_gap_exactly_at_threshold_is_complete(self):
        # duration_sec=0 keeps the math exact: gap is precisely 6h.
        sessions = [
            make_session(DAY_START, 0.0, "s1"),
            make_session(DAY_START + timedelta(hours=6), 0.0, "s2"),
        ]
        result = assess_day_completeness(sessions, max_gap_hours=6.0)
        assert result.is_complete is True

    def test_gap_across_multiple_apps_still_counts(self):
        # The whole point of this function: gaps must be measured
        # across ALL apps for the user, not per-app.
        sessions = [
            make_session(DAY_START + timedelta(hours=9), 600.0, "s1", package="com.whatsapp"),
            make_session(
                DAY_START + timedelta(hours=20), 600.0, "s2", package="com.instagram.android"
            ),
        ]
        result = assess_day_completeness(sessions)
        assert result.is_complete is False

    def test_single_session_has_zero_max_gap(self):
        sessions = [make_session(DAY_START + timedelta(hours=9), 600.0, "s1")]
        result = assess_day_completeness(sessions)
        assert result.max_gap_hours == 0.0
        assert result.is_complete is True


class TestCustomThreshold:
    def test_custom_stricter_threshold_flags_smaller_gaps(self):
        sessions = [
            make_session(DAY_START, 0.0, "s1"),
            make_session(DAY_START + timedelta(hours=3), 0.0, "s2"),
        ]
        # 3-hour gap passes the 6-hour default...
        assert assess_day_completeness(sessions).is_complete is True
        # ...but fails a stricter 2-hour threshold.
        assert assess_day_completeness(sessions, max_gap_hours=2.0).is_complete is False


class TestResultFields:
    def test_result_carries_correct_user_and_day(self):
        sessions = [make_session(DAY_START + timedelta(hours=9), 600.0, "s1")]
        result = assess_day_completeness(sessions)
        assert result.user_id == "u1"
        assert result.day == DAY_START.date()

    def test_incomplete_reason_mentions_uncertainty(self):
        # The reason string must not overclaim — it should not assert
        # a sync failure happened, only that this heuristic can't tell
        # the difference from genuine non-use.
        sessions = [
            make_session(DAY_START, 0.0, "s1"),
            make_session(DAY_START + timedelta(hours=10), 0.0, "s2"),
        ]
        result = assess_day_completeness(sessions)
        assert "cannot tell the difference" in result.reason