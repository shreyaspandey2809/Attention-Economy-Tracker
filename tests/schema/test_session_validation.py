from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from attention_tracker.schema.session import Session


def make_kwargs(**overrides):
    start = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)
    base = dict(
        user_id="user_001",
        package_name="com.instagram.android",
        session_id="sess_abc123",
        start_time=start,
        end_time=start + timedelta(seconds=90),
        duration_sec=90.0,
    )
    base.update(overrides)
    return base


class TestValidSessions:
    def test_valid_session(self):
        session = Session(**make_kwargs())
        assert session.duration_sec == 90.0

    def test_session_with_transitions(self):
        session = Session(
            **make_kwargs(
                transition_from="com.android.chrome",
                transition_to="com.whatsapp",
            )
        )
        assert session.transition_from == "com.android.chrome"
        assert session.transition_to == "com.whatsapp"

    def test_session_without_transitions_allowed(self):
        session = Session(**make_kwargs())
        assert session.transition_from is None
        assert session.transition_to is None

    def test_small_float_slack_in_duration_allowed(self):
        # 90.4s actual vs 90.0s reported duration — within 1.0s slack
        start = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)
        session = Session(
            **make_kwargs(
                start_time=start,
                end_time=start + timedelta(seconds=90.4),
                duration_sec=90.0,
            )
        )
        assert session.duration_sec == 90.0


class TestMalformedSessions:
    def test_naive_start_time_rejected(self):
        with pytest.raises(ValidationError, match="timezone-aware"):
            Session(**make_kwargs(start_time=datetime(2026, 8, 7, 10, 0, 0)))

    def test_end_before_start_rejected(self):
        start = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="end_time"):
            Session(
                **make_kwargs(
                    start_time=start,
                    end_time=start - timedelta(seconds=10),
                    duration_sec=10.0,
                )
            )

    def test_duration_inconsistent_with_timestamps_rejected(self):
        start = datetime(2026, 8, 7, 10, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="inconsistent"):
            Session(
                **make_kwargs(
                    start_time=start,
                    end_time=start + timedelta(seconds=90),
                    duration_sec=5000.0,  # wildly inconsistent
                )
            )

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            Session(**make_kwargs(duration_sec=-1.0))

    def test_empty_session_id_rejected(self):
        with pytest.raises(ValidationError):
            Session(**make_kwargs(session_id=""))
