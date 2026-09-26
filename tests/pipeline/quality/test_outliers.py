from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.pipeline.quality.outliers import (
    MAX_PLAUSIBLE_SESSION_SEC,
    cap_session_outliers,
)
from attention_tracker.schema.session import Session

START = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)


def make_session(
    duration_sec: float,
    session_id: str = "sess_1",
    user_id: str = "user_1",
    start: datetime = START,
) -> Session:
    return Session(
        user_id=user_id,
        package_name="com.instagram.android",
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
    )


class TestMeasurementErrorIsCapped:
    def test_stale_wakelock_style_session_is_capped(self):
        # The State-and-Plan's own example: a 14-hour session from a
        # stale wake-lock. Must be capped, not passed through.
        fourteen_hours = 14 * 60 * 60
        session = make_session(fourteen_hours, "sess_wakelock")

        result = cap_session_outliers([session])

        assert result.capped_count == 1
        assert result.capped_session_ids == ["sess_wakelock"]
        assert result.sessions[0].duration_sec == MAX_PLAUSIBLE_SESSION_SEC

    def test_capped_session_end_time_stays_consistent_with_duration(self):
        session = make_session(14 * 60 * 60, "sess_wakelock")
        result = cap_session_outliers([session])
        capped = result.sessions[0]
        # Session's own validator enforces end_time - start_time ==
        # duration_sec within slack — re-validating here confirms we
        # didn't produce an internally inconsistent Session.
        recomputed = (capped.end_time - capped.start_time).total_seconds()
        assert abs(recomputed - capped.duration_sec) < 1.0

    def test_session_exactly_at_boundary_is_not_capped(self):
        session = make_session(MAX_PLAUSIBLE_SESSION_SEC, "sess_boundary")
        result = cap_session_outliers([session])
        assert result.capped_count == 0
        assert result.sessions[0].duration_sec == MAX_PLAUSIBLE_SESSION_SEC


class TestGenuineHeavyUsageSurvivesUncapped:
    @pytest.mark.parametrize(
        "duration_sec",
        [
            600.0,     # DOOMSCROLLER's designed mean session length
            1800.0,    # a long but plausible 30-minute binge session
            3600.0,    # a full uninterrupted hour — still device-plausible
            13800.0,   # just under the 4-hour cap
        ],
    )
    def test_plausible_heavy_session_is_not_capped(self, duration_sec):
        session = make_session(duration_sec, "sess_heavy")
        result = cap_session_outliers([session])
        assert result.capped_count == 0
        assert result.sessions[0].duration_sec == duration_sec
        assert result.sessions[0].end_time == session.end_time

    def test_mixed_batch_only_caps_the_implausible_one(self):
        normal = make_session(600.0, "sess_normal")
        heavy_but_real = make_session(3600.0, "sess_heavy_real")
        wakelock_bug = make_session(14 * 60 * 60, "sess_bug")

        result = cap_session_outliers([normal, heavy_but_real, wakelock_bug])

        assert result.capped_count == 1
        assert result.capped_session_ids == ["sess_bug"]
        by_id = {s.session_id: s for s in result.sessions}
        assert by_id["sess_normal"].duration_sec == 600.0
        assert by_id["sess_heavy_real"].duration_sec == 3600.0
        assert by_id["sess_bug"].duration_sec == MAX_PLAUSIBLE_SESSION_SEC


class TestEmptyAndCustomBounds:
    def test_empty_session_list_returns_empty_result(self):
        result = cap_session_outliers([])
        assert result.sessions == []
        assert result.capped_count == 0

    def test_custom_bound_is_respected(self):
        session = make_session(100.0, "sess_short")
        result = cap_session_outliers([session], max_plausible_sec=50.0)
        assert result.capped_count == 1
        assert result.sessions[0].duration_sec == 50.0


class TestOverlapDetection:

    def test_two_overlapping_sessions_for_same_user_are_flagged(self):
        a = make_session(3600.0, "a", start=START)  # 10:00-11:00
        b = make_session(600.0, "b", start=START + timedelta(minutes=50))  # 10:50-11:00
        result = cap_session_outliers([a, b])
        assert result.overlapping_session_ids == [("a", "b")]

    def test_non_overlapping_sessions_are_not_flagged(self):
        a = make_session(600.0, "a", start=START)
        b = make_session(600.0, "b", start=START + timedelta(minutes=20))
        result = cap_session_outliers([a, b])
        assert result.overlapping_session_ids == []

    def test_sessions_that_exactly_touch_are_not_flagged(self):
        a = make_session(600.0, "a", start=START)  # ends at START+10min
        b = make_session(600.0, "b", start=START + timedelta(minutes=10))
        result = cap_session_outliers([a, b])
        assert result.overlapping_session_ids == []

    def test_overlap_across_different_users_is_not_flagged(self):
        a = make_session(3600.0, "a", start=START, user_id="user_1")
        b = make_session(600.0, "b", start=START + timedelta(minutes=50), user_id="user_2")
        result = cap_session_outliers([a, b])
        assert result.overlapping_session_ids == []

    def test_long_session_containing_two_non_adjacent_short_sessions_flags_both(self):
        a = make_session(6000.0, "a", start=START)
        b = make_session(600.0, "b", start=START + timedelta(minutes=10))
        c = make_session(600.0, "c", start=START + timedelta(minutes=30))
        result = cap_session_outliers([a, b, c])
        assert set(result.overlapping_session_ids) == {("a", "b"), ("a", "c")}

    def test_capping_a_session_can_remove_a_would_be_overlap(self):
        a = make_session(14 * 60 * 60, "a", start=START)
        b = make_session(600.0, "b", start=START + timedelta(hours=5))
        result = cap_session_outliers([a, b])
        assert result.overlapping_session_ids == []

    def test_empty_and_single_session_have_no_overlaps(self):
        assert cap_session_outliers([]).overlapping_session_ids == []
        assert cap_session_outliers(
            [make_session(600.0, "a")]
        ).overlapping_session_ids == []