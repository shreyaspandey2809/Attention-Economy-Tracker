"""
Per synopsis Ch. 10.1: each schema validator is tested against both
valid and deliberately malformed inputs — naive timestamps, terminal
events missing duration/session_id, opening events incorrectly
carrying a duration — confirming the boundary rejects bad data rather
than letting it propagate downstream.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from attention_tracker.schema.raw_event import EventType, RawEvent


def make_kwargs(**overrides):
    base = dict(
        user_id="user_001",
        package_name="com.instagram.android",
        event_type=EventType.OPENED,
        timestamp=datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc),
        tz_offset_minutes=330,
    )
    base.update(overrides)
    return base


class TestValidEvents:
    def test_valid_opening_event(self):
        event = RawEvent(**make_kwargs(event_type=EventType.OPENED))
        assert event.session_duration_sec is None
        assert event.session_id is None

    def test_valid_foreground_event(self):
        event = RawEvent(**make_kwargs(event_type=EventType.FOREGROUND))
        assert event.session_duration_sec is None

    def test_valid_closed_event(self):
        event = RawEvent(
            **make_kwargs(
                event_type=EventType.CLOSED,
                session_duration_sec=42.5,
                session_id="sess_abc123",
            )
        )
        assert event.session_duration_sec == 42.5
        assert event.session_id == "sess_abc123"

    def test_valid_background_event(self):
        event = RawEvent(
            **make_kwargs(
                event_type=EventType.BACKGROUND,
                session_duration_sec=10.0,
                session_id="sess_xyz",
            )
        )
        assert event.event_type == EventType.BACKGROUND

    def test_timestamp_normalized_to_utc(self):
        from datetime import timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        local_ts = datetime(2026, 8, 7, 15, 30, 0, tzinfo=ist)
        event = RawEvent(**make_kwargs(timestamp=local_ts))
        assert event.timestamp.tzinfo == timezone.utc
        assert event.timestamp.hour == 10  # 15:30 IST -> 10:00 UTC


class TestMalformedEvents:
    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            RawEvent(**make_kwargs(timestamp=datetime(2026, 8, 7, 10, 0, 0)))

    def test_terminal_event_missing_duration_rejected(self):
        with pytest.raises(ValidationError, match="session_duration_sec"):
            RawEvent(
                **make_kwargs(
                    event_type=EventType.CLOSED,
                    session_id="sess_abc123",
                    # session_duration_sec deliberately omitted
                )
            )

    def test_terminal_event_missing_session_id_rejected(self):
        with pytest.raises(ValidationError, match="session_id"):
            RawEvent(
                **make_kwargs(
                    event_type=EventType.CLOSED,
                    session_duration_sec=30.0,
                    # session_id deliberately omitted
                )
            )

    def test_opening_event_with_duration_rejected(self):
        with pytest.raises(ValidationError, match="must not carry"):
            RawEvent(
                **make_kwargs(
                    event_type=EventType.OPENED,
                    session_duration_sec=15.0,
                )
            )

    def test_opening_event_with_session_id_rejected(self):
        with pytest.raises(ValidationError, match="must not carry"):
            RawEvent(
                **make_kwargs(
                    event_type=EventType.FOREGROUND,
                    session_id="sess_should_not_exist",
                )
            )

    def test_empty_user_id_rejected(self):
        with pytest.raises(ValidationError):
            RawEvent(**make_kwargs(user_id=""))

    def test_tz_offset_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            RawEvent(**make_kwargs(tz_offset_minutes=1000))

    def test_negative_session_duration_rejected(self):
        with pytest.raises(ValidationError):
            RawEvent(
                **make_kwargs(
                    event_type=EventType.CLOSED,
                    session_duration_sec=-5.0,
                    session_id="sess_neg",
                )
            )

    def test_unknown_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            RawEvent(**make_kwargs(some_unexpected_field="oops"))
