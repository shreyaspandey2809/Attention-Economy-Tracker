import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.synthetic.archetypes import ARCHETYPES, BALANCED, DOOMSCROLLER
from attention_tracker.synthetic.generator import SyntheticEventGenerator


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


@pytest.fixture
def generator(taxonomy: TaxonomyLoader) -> SyntheticEventGenerator:
    return SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(42))


DAY_START = datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc)  # a Monday


class TestGeneratorStructuralValidity:
    def test_generate_day_returns_raw_events(self, generator: SyntheticEventGenerator):
        events = generator.generate_day("user_bal", BALANCED, DAY_START)
        assert len(events) > 0
        assert all(isinstance(e, RawEvent) for e in events)

    def test_events_come_in_opened_closed_pairs(
        self, generator: SyntheticEventGenerator
    ):
        events = generator.generate_day("user_bal", BALANCED, DAY_START)
        assert len(events) % 2 == 0
        for i in range(0, len(events), 2):
            assert events[i].event_type == EventType.OPENED
            assert events[i + 1].event_type == EventType.CLOSED
            assert events[i].package_name == events[i + 1].package_name

    def test_closed_event_duration_matches_timestamp_gap(
        self, generator: SyntheticEventGenerator
    ):
        events = generator.generate_day("user_bal", BALANCED, DAY_START)
        for i in range(0, len(events), 2):
            opened, closed = events[i], events[i + 1]
            gap = (closed.timestamp - opened.timestamp).total_seconds()
            assert abs(gap - closed.session_duration_sec) < 0.01

    def test_multi_day_generation_is_chronologically_sorted(
        self, generator: SyntheticEventGenerator
    ):
        events = generator.generate("user_bal", BALANCED, DAY_START, num_days=5)
        timestamps = [e.timestamp for e in events]
        assert timestamps == sorted(timestamps)

    def test_multi_day_spans_requested_range(
        self, generator: SyntheticEventGenerator
    ):
        events = generator.generate("user_bal", BALANCED, DAY_START, num_days=3)
        first_day = events[0].timestamp.date()
        last_day = events[-1].timestamp.date()
        assert (last_day - first_day).days <= 3  # late-night spillover allowed

    def test_all_archetypes_registered(self):
        assert set(ARCHETYPES.keys()) == {
            "BALANCED",
            "DOOMSCROLLER",
            "BINGE_WEEKEND",
            "DEEP_WORKER",
            "COMPULSIVE_CHECKER",
        }
        assert ARCHETYPES["BALANCED"] is BALANCED
        assert ARCHETYPES["DOOMSCROLLER"] is DOOMSCROLLER

    def test_naive_day_start_rejected(self, generator: SyntheticEventGenerator):
        with pytest.raises(ValueError, match="timezone-aware"):
            generator.generate_day("user_bal", BALANCED, datetime(2026, 8, 3))

    def test_sessions_never_overlap(self, generator: SyntheticEventGenerator):
        events = generator.generate("user_doom", DOOMSCROLLER, DAY_START, num_days=10)
        closed_events = [e for e in events if e.event_type == EventType.CLOSED]
        opened_events = [e for e in events if e.event_type == EventType.OPENED]

        sessions = sorted(
            zip(opened_events, closed_events), key=lambda pair: pair[0].timestamp
        )
        for i in range(len(sessions) - 1):
            _, current_close = sessions[i]
            next_open, _ = sessions[i + 1]
            assert next_open.timestamp >= current_close.timestamp


class TestArchetypeSeparation:
    @pytest.fixture
    def balanced_week(self, taxonomy: TaxonomyLoader) -> list[RawEvent]:
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(7))
        return gen.generate("user_bal", BALANCED, DAY_START, num_days=14)

    @pytest.fixture
    def doomscroller_week(self, taxonomy: TaxonomyLoader) -> list[RawEvent]:
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(7))
        return gen.generate("user_doom", DOOMSCROLLER, DAY_START, num_days=14)

    def _addictive_time_fraction(
        self, events: list[RawEvent], taxonomy: TaxonomyLoader
    ) -> float:
        total = 0.0
        addictive = 0.0
        for e in events:
            if e.event_type != EventType.CLOSED:
                continue
            total += e.session_duration_sec
            if taxonomy.lookup(e.package_name).category == AppCategory.ADDICTIVE:
                addictive += e.session_duration_sec
        return addictive / total if total else 0.0

    def _late_night_fraction(self, events: list[RawEvent]) -> float:
        opens = [e for e in events if e.event_type == EventType.OPENED]
        if not opens:
            return 0.0
        late = sum(1 for e in opens if e.timestamp.hour in (23, 0, 1, 2, 3))
        return late / len(opens)

    def test_doomscroller_has_more_addictive_time_than_balanced(
        self,
        balanced_week: list[RawEvent],
        doomscroller_week: list[RawEvent],
        taxonomy: TaxonomyLoader,
    ):
        bal_frac = self._addictive_time_fraction(balanced_week, taxonomy)
        doom_frac = self._addictive_time_fraction(doomscroller_week, taxonomy)
        assert doom_frac > bal_frac
        # Sanity-check the gap is substantial, not marginal noise.
        assert doom_frac - bal_frac > 0.2

    def test_doomscroller_has_more_late_night_sessions_than_balanced(
        self, balanced_week: list[RawEvent], doomscroller_week: list[RawEvent]
    ):
        bal_late = self._late_night_fraction(balanced_week)
        doom_late = self._late_night_fraction(doomscroller_week)
        assert doom_late > bal_late

    def test_doomscroller_sessions_are_longer_on_average(
        self, balanced_week: list[RawEvent], doomscroller_week: list[RawEvent]
    ):
        def avg_duration(events: list[RawEvent]) -> float:
            durations = [
                e.session_duration_sec
                for e in events
                if e.event_type == EventType.CLOSED
            ]
            return sum(durations) / len(durations)

        assert avg_duration(doomscroller_week) > avg_duration(balanced_week)


class TestLateNightHourDistribution:

    def test_hour_0_is_not_systematically_starved(self, taxonomy: TaxonomyLoader):
        # Directly exercise the sampler (bypassing the cursor) across
        # many draws to isolate the day-placement logic itself.
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(7))
        hour_counts = {h: 0 for h in (23, 0, 1, 2, 3)}
        for _ in range(20_000):
            forced_late_night = replace(
                DOOMSCROLLER, late_night_session_fraction=1.0
            )
            start = gen._sample_start_time(DAY_START, forced_late_night)
            if start.hour in hour_counts:
                hour_counts[start.hour] += 1

        total = sum(hour_counts.values())
        assert total == 20_000
        for hour, count in hour_counts.items():
            share = count / total
            assert 0.15 < share < 0.25, (
                f"hour {hour} got {share:.1%} of late-night draws, "
                "expected roughly 20% (even split across 5 hours)"
            )

    def test_hour_0_lands_on_the_day_after_day_start(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(0))
        forced_late_night = replace(DOOMSCROLLER, late_night_session_fraction=1.0)
        found_hour_0 = False
        for _ in range(500):
            start = gen._sample_start_time(DAY_START, forced_late_night)
            if start.hour == 0:
                found_hour_0 = True
                assert start.date() == DAY_START.date() + timedelta(days=1)
        assert found_hour_0, "test didn't sample hour 0 in 500 draws — flaky seed"

    def test_full_day_generation_late_night_fraction_matches_profile_design(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(3))
        events = gen.generate("user_doom", DOOMSCROLLER, DAY_START, num_days=30)
        opens = [e for e in events if e.event_type == EventType.OPENED]
        late = sum(1 for e in opens if e.timestamp.hour in (23, 0, 1, 2, 3))
        measured = late / len(opens)
        assert abs(measured - DOOMSCROLLER.late_night_session_fraction) < 0.05