from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.pipeline.features.transitions import (
    productive_interruption_rate,
)
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

T0 = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

PRODUCTIVE_APP = "com.google.android.apps.docs"  # PRODUCTIVE in the seed taxonomy
ENTERTAINMENT_APP = "com.netflix.mediaclient"  # ENTERTAINMENT in the seed taxonomy


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


def make_session(transition_from, session_id, start=T0, duration_sec=60.0):
    return Session(
        user_id="u1",
        package_name="com.instagram.android",
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
        transition_from=transition_from,
    )


class TestProductiveInterruptionRate:
    def test_empty_list_raises(self, taxonomy):
        with pytest.raises(ValueError, match="at least one session"):
            productive_interruption_rate([], taxonomy)

    def test_no_eligible_sessions_returns_zero(self, taxonomy):
        # Every session is the user's first of the day (no transition_from).
        sessions = [make_session(None, "s1"), make_session(None, "s2")]
        assert productive_interruption_rate(sessions, taxonomy) == 0.0

    def test_all_interruptions_from_productive_apps(self, taxonomy):
        sessions = [
            make_session(PRODUCTIVE_APP, "s1"),
            make_session(PRODUCTIVE_APP, "s2"),
        ]
        assert productive_interruption_rate(sessions, taxonomy) == 1.0

    def test_no_interruptions_from_productive_apps(self, taxonomy):
        sessions = [
            make_session(ENTERTAINMENT_APP, "s1"),
            make_session(ENTERTAINMENT_APP, "s2"),
        ]
        assert productive_interruption_rate(sessions, taxonomy) == 0.0

    def test_mixed_transitions_gives_correct_ratio(self, taxonomy):
        sessions = [
            make_session(PRODUCTIVE_APP, "s1"),
            make_session(ENTERTAINMENT_APP, "s2"),
            make_session(PRODUCTIVE_APP, "s3"),
            make_session(ENTERTAINMENT_APP, "s4"),
        ]
        assert productive_interruption_rate(sessions, taxonomy) == 0.5

    def test_none_transitions_excluded_from_denominator(self, taxonomy):
        # 1 productive interruption, 1 non-productive, 1 with no
        # prior session at all — denominator should be 2, not 3.
        sessions = [
            make_session(PRODUCTIVE_APP, "s1"),
            make_session(ENTERTAINMENT_APP, "s2"),
            make_session(None, "s3"),
        ]
        assert productive_interruption_rate(sessions, taxonomy) == 0.5

    def test_unknown_package_in_transition_from_is_not_productive(self, taxonomy):
        # An app not in the seed taxonomy falls back to UNKNOWN
        # category (per taxonomy_loader.py's documented behavior),
        # which must not be counted as a productive interruption.
        sessions = [make_session("com.some.unknown.app.xyz", "s1")]
        assert productive_interruption_rate(sessions, taxonomy) == 0.0