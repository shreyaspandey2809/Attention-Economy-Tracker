from datetime import datetime, timedelta, timezone

from attention_tracker.pipeline.quality.outliers import MAX_PLAUSIBLE_SESSION_SEC
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.schema.raw_event import EventType, RawEvent

T0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)


def opened(user_id, package_name, ts, tz_offset=0):
    return RawEvent(
        user_id=user_id,
        package_name=package_name,
        event_type=EventType.OPENED,
        timestamp=ts,
        tz_offset_minutes=tz_offset,
    )


def closed(user_id, package_name, ts, duration, session_id, tz_offset=0):
    return RawEvent(
        user_id=user_id,
        package_name=package_name,
        event_type=EventType.CLOSED,
        timestamp=ts,
        tz_offset_minutes=tz_offset,
        session_duration_sec=duration,
        session_id=session_id,
    )


class TestPipelineOrdering:
    def test_stages_run_in_dedup_then_build_then_cap_order(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            opened("u1", "com.whatsapp", T0),  # exact duplicate
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
        ]

        result = run_data_quality_pipeline(events)

        assert len(result.sessions) == 1
        assert result.dedup_result.duplicate_count == 2

    def test_wake_lock_session_is_capped_after_building(self):
        fourteen_hours = 14 * 60 * 60
        events = [
            opened("u1", "com.instagram.android", T0),
            closed(
                "u1",
                "com.instagram.android",
                T0 + timedelta(seconds=fourteen_hours),
                fourteen_hours,
                "sess_wakelock",
            ),
        ]

        result = run_data_quality_pipeline(events)

        assert len(result.sessions) == 1
        assert result.sessions[0].duration_sec == MAX_PLAUSIBLE_SESSION_SEC
        assert result.outlier_result.capped_count == 1
        assert result.outlier_result.capped_session_ids == ["sess_wakelock"]

    def test_duplicate_and_outlier_both_present_are_both_handled(self):
        fourteen_hours = 14 * 60 * 60
        events = [
            opened("u1", "com.whatsapp", T0),
            opened("u1", "com.whatsapp", T0),  # duplicate open
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            opened("u1", "com.instagram.android", T0 + timedelta(minutes=5)),
            closed(
                "u1",
                "com.instagram.android",
                T0 + timedelta(minutes=5, seconds=fourteen_hours),
                fourteen_hours,
                "sess_wakelock",
            ),
        ]

        result = run_data_quality_pipeline(events)

        assert len(result.sessions) == 2
        assert result.dedup_result.duplicate_count == 1
        assert result.outlier_result.capped_count == 1

        by_package = {s.package_name: s for s in result.sessions}
        assert by_package["com.whatsapp"].duration_sec == 30.0
        assert by_package["com.instagram.android"].duration_sec == (
            MAX_PLAUSIBLE_SESSION_SEC
        )


class TestPipelinePassthrough:
    def test_clean_input_passes_through_with_no_changes(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
        ]

        result = run_data_quality_pipeline(events)

        assert len(result.sessions) == 1
        assert result.dedup_result.duplicate_count == 0
        assert result.outlier_result.capped_count == 0
        assert not result.build_result.unmatched_opens
        assert not result.build_result.unmatched_closes

    def test_empty_input_returns_empty_result(self):
        result = run_data_quality_pipeline([])
        assert result.sessions == []
        assert result.dedup_result.duplicate_count == 0
        assert result.outlier_result.capped_count == 0

    def test_unmatched_events_still_surfaced_through_build_result(self):
        events = [closed("u1", "com.whatsapp", T0, 30.0, "s1")]

        result = run_data_quality_pipeline(events)

        assert result.sessions == []
        assert len(result.build_result.unmatched_closes) == 1


class TestCustomOutlierBound:
    def test_custom_max_plausible_sec_is_respected(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=100), 100.0, "s1"),
        ]

        result = run_data_quality_pipeline(events, max_plausible_session_sec=50.0)

        assert result.sessions[0].duration_sec == 50.0
        assert result.outlier_result.capped_count == 1