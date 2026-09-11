from datetime import datetime, timedelta, timezone

from attention_tracker.pipeline.quality.dedup import dedupe_events
from attention_tracker.schema.raw_event import EventType, RawEvent

START = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)


def make_open(
    user_id="user_1", package="com.instagram.android", timestamp=START
) -> RawEvent:
    return RawEvent(
        user_id=user_id,
        package_name=package,
        event_type=EventType.OPENED,
        timestamp=timestamp,
        tz_offset_minutes=330,
    )


def make_close(
    user_id="user_1",
    package="com.instagram.android",
    timestamp=START + timedelta(seconds=60),
    session_id="sess_1",
    duration_sec=60.0,
) -> RawEvent:
    return RawEvent(
        user_id=user_id,
        package_name=package,
        event_type=EventType.CLOSED,
        timestamp=timestamp,
        tz_offset_minutes=330,
        session_duration_sec=duration_sec,
        session_id=session_id,
    )


class TestTerminalEventDedup:
    def test_resent_terminal_event_with_same_session_id_is_dropped(self):
        original = make_close(session_id="sess_1")
        # A WorkManager retry resends the exact same CLOSED event.
        retry = make_close(session_id="sess_1")

        result = dedupe_events([original, retry])

        assert len(result.events) == 1
        assert result.duplicate_count == 1
        assert result.duplicate_session_ids == ["sess_1"]

    def test_different_session_ids_are_both_kept(self):
        first = make_close(session_id="sess_1")
        second = make_close(
            timestamp=START + timedelta(minutes=5), session_id="sess_2"
        )

        result = dedupe_events([first, second])

        assert len(result.events) == 2
        assert result.duplicate_count == 0

    def test_background_events_deduped_the_same_way_as_closed(self):
        original = RawEvent(
            user_id="user_1",
            package_name="com.instagram.android",
            event_type=EventType.BACKGROUND,
            timestamp=START,
            tz_offset_minutes=330,
            session_duration_sec=30.0,
            session_id="sess_bg",
        )
        retry = RawEvent(
            user_id="user_1",
            package_name="com.instagram.android",
            event_type=EventType.BACKGROUND,
            timestamp=START,
            tz_offset_minutes=330,
            session_duration_sec=30.0,
            session_id="sess_bg",
        )

        result = dedupe_events([original, retry])

        assert len(result.events) == 1
        assert result.duplicate_session_ids == ["sess_bg"]

    def test_first_seen_terminal_event_wins_and_order_preserved(self):
        first = make_close(session_id="sess_1", duration_sec=60.0)
        retry = make_close(session_id="sess_1", duration_sec=999.0)

        result = dedupe_events([first, retry])

        assert len(result.events) == 1
        # First-seen wins: the retry's (different) duration must not
        # overwrite the original.
        assert result.events[0].session_duration_sec == 60.0


class TestOpeningEventDedup:
    def test_resent_opening_event_with_same_key_is_dropped(self):
        original = make_open()
        # An overlapping UsageStatsManager query window re-emits the
        # same OPENED event.
        retry = make_open()

        result = dedupe_events([original, retry])

        assert len(result.events) == 1
        assert result.duplicate_count == 1
        assert result.duplicate_open_keys == [
            ("user_1", "com.instagram.android", START.isoformat())
        ]

    def test_different_timestamp_is_not_a_duplicate(self):
        first = make_open(timestamp=START)
        second = make_open(timestamp=START + timedelta(seconds=1))

        result = dedupe_events([first, second])

        assert len(result.events) == 2
        assert result.duplicate_count == 0

    def test_different_package_at_same_timestamp_is_not_a_duplicate(self):
        first = make_open(package="com.instagram.android")
        second = make_open(package="com.whatsapp")

        result = dedupe_events([first, second])

        assert len(result.events) == 2

    def test_different_user_at_same_timestamp_and_package_is_not_a_duplicate(self):
        first = make_open(user_id="user_1")
        second = make_open(user_id="user_2")

        result = dedupe_events([first, second])

        assert len(result.events) == 2


class TestMixedStreamAndPassthrough:
    def test_no_duplicates_passes_every_event_through_unchanged(self):
        events = [
            make_open(timestamp=START),
            make_close(timestamp=START + timedelta(seconds=60), session_id="sess_1"),
        ]

        result = dedupe_events(events)

        assert result.events == events
        assert result.duplicate_count == 0

    def test_mixed_stream_dedupes_both_shapes_independently(self):
        open_1 = make_open(timestamp=START)
        open_1_retry = make_open(timestamp=START)
        close_1 = make_close(
            timestamp=START + timedelta(seconds=60), session_id="sess_1"
        )
        close_1_retry = make_close(
            timestamp=START + timedelta(seconds=60), session_id="sess_1"
        )
        open_2 = make_open(timestamp=START + timedelta(minutes=5))

        result = dedupe_events(
            [open_1, open_1_retry, close_1, close_1_retry, open_2]
        )

        assert len(result.events) == 3  # open_1, close_1, open_2
        assert result.duplicate_count == 2

    def test_empty_event_list_returns_empty_result(self):
        result = dedupe_events([])
        assert result.events == []
        assert result.duplicate_count == 0