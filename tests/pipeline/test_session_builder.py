import random
from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.synthetic.archetypes import BALANCED
from attention_tracker.synthetic.generator import SyntheticEventGenerator
from attention_tracker.pipeline.session_builder import SessionBuilder

T0 = datetime(2026, 8, 10, 9, 0, 0, tzinfo=timezone.utc)  # a Monday


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


class TestBasicPairing:
    def test_single_session_pairs_correctly(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
        ]
        result = SessionBuilder().build(events)

        assert len(result.sessions) == 1
        assert not result.unmatched_opens
        assert not result.unmatched_closes

        session = result.sessions[0]
        assert session.user_id == "u1"
        assert session.package_name == "com.whatsapp"
        assert session.session_id == "s1"
        assert session.duration_sec == 30.0

    def test_multiple_sequential_sessions(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            opened("u1", "com.instagram.android", T0 + timedelta(seconds=40)),
            closed(
                "u1",
                "com.instagram.android",
                T0 + timedelta(seconds=340),
                300.0,
                "s2",
            ),
        ]
        result = SessionBuilder().build(events)

        assert len(result.sessions) == 2
        assert not result.unmatched_opens
        assert not result.unmatched_closes


class TestTransitionAssignment:
    def test_three_sessions_get_correct_transitions(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            opened("u1", "com.instagram.android", T0 + timedelta(seconds=40)),
            closed(
                "u1",
                "com.instagram.android",
                T0 + timedelta(seconds=340),
                300.0,
                "s2",
            ),
            opened("u1", "com.android.chrome", T0 + timedelta(seconds=350)),
            closed(
                "u1", "com.android.chrome", T0 + timedelta(seconds=410), 60.0, "s3"
            ),
        ]
        result = SessionBuilder().build(events)
        sessions = result.sessions
        assert len(sessions) == 3

        whatsapp, instagram, chrome = sessions

        assert whatsapp.transition_from is None
        assert whatsapp.transition_to == "com.instagram.android"

        assert instagram.transition_from == "com.whatsapp"
        assert instagram.transition_to == "com.android.chrome"

        assert chrome.transition_from == "com.instagram.android"
        assert chrome.transition_to is None

    def test_single_session_has_no_transitions(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
        ]
        result = SessionBuilder().build(events)
        session = result.sessions[0]
        assert session.transition_from is None
        assert session.transition_to is None


class TestMultiUserIsolation:
    def test_transitions_do_not_cross_users(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            opened("u2", "com.android.chrome", T0 + timedelta(seconds=35)),
            closed(
                "u2", "com.android.chrome", T0 + timedelta(seconds=95), 60.0, "s2"
            ),
        ]
        result = SessionBuilder().build(events)
        assert len(result.sessions) == 2

        u1_session = next(s for s in result.sessions if s.user_id == "u1")
        u2_session = next(s for s in result.sessions if s.user_id == "u2")

        # Even though u2's session starts right after u1's session
        # ends chronologically, they must NOT be treated as a
        # transition into/out of each other — different users.
        assert u1_session.transition_to is None
        assert u2_session.transition_from is None


class TestUnmatchedEvents:
    def test_unclosed_session_is_unmatched_open_not_a_session(self):
        events = [opened("u1", "com.whatsapp", T0)]
        result = SessionBuilder().build(events)
        assert result.sessions == []
        assert len(result.unmatched_opens) == 1
        assert result.unmatched_opens[0].package_name == "com.whatsapp"

    def test_close_with_no_preceding_open_is_unmatched_close(self):
        events = [closed("u1", "com.whatsapp", T0, 30.0, "s1")]
        result = SessionBuilder().build(events)
        assert result.sessions == []
        assert len(result.unmatched_closes) == 1

    def test_mixed_matched_and_unmatched(self):
        events = [
            opened("u1", "com.whatsapp", T0),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=30), 30.0, "s1"),
            # This OPENED never closes within the window.
            opened("u1", "com.instagram.android", T0 + timedelta(seconds=40)),
        ]
        result = SessionBuilder().build(events)
        assert len(result.sessions) == 1
        assert len(result.unmatched_opens) == 1
        assert result.unmatched_opens[0].package_name == "com.instagram.android"

    def test_fifo_pairing_on_rapid_reopen(self):
        """Two OPENED for the same app before either CLOSED arrives —
        must pair first-open-with-first-close (FIFO), not last-with-first."""
        events = [
            opened("u1", "com.whatsapp", T0),
            opened("u1", "com.whatsapp", T0 + timedelta(seconds=5)),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=10), 10.0, "s1"),
            closed("u1", "com.whatsapp", T0 + timedelta(seconds=20), 15.0, "s2"),
        ]
        result = SessionBuilder().build(events)
        assert len(result.sessions) == 2
        # FIFO: first open (T0) pairs with first close (s1, at +10s).
        first, second = sorted(result.sessions, key=lambda s: s.start_time)
        assert first.start_time == T0
        assert first.session_id == "s1"
        assert second.start_time == T0 + timedelta(seconds=5)
        assert second.session_id == "s2"


class TestRoundTripWithSyntheticGenerator:
    """Full pipeline check: every event the generator produces should
    be cleanly paired by the builder, with zero unmatched events,
    since the generator always emits strict OPENED-then-CLOSED pairs."""

    @pytest.fixture
    def taxonomy(self) -> TaxonomyLoader:
        return TaxonomyLoader()

    def test_multi_day_balanced_stream_has_zero_unmatched_events(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(123))
        events = gen.generate("user_bal", BALANCED, T0, num_days=10)

        result = SessionBuilder().build(events)

        assert not result.unmatched_opens
        assert not result.unmatched_closes
        assert len(result.sessions) == len(events) // 2

    def test_sessions_are_chronologically_sorted(self, taxonomy: TaxonomyLoader):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(123))
        events = gen.generate("user_bal", BALANCED, T0, num_days=5)

        result = SessionBuilder().build(events)
        starts = [s.start_time for s in result.sessions]
        assert starts == sorted(starts)

    def test_transitions_chain_correctly_across_full_stream(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(123))
        events = gen.generate("user_bal", BALANCED, T0, num_days=5)

        result = SessionBuilder().build(events)
        sessions = result.sessions

        # Every session's transition_to should equal the NEXT
        # session's own package_name, except the very last.
        for i in range(len(sessions) - 1):
            assert sessions[i].transition_to == sessions[i + 1].package_name
            assert sessions[i + 1].transition_from == sessions[i].package_name

        assert sessions[0].transition_from is None
        assert sessions[-1].transition_to is None