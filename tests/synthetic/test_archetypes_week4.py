"""
Week 4 additions to the synthetic generator test suite:
- BINGE_WEEKEND and DEEP_WORKER archetypes exist and are structurally
  valid (same bar as Week 3's archetypes).
- The weekend multiplier mechanism actually produces a measurable
  weekday/weekend split for BINGE_WEEKEND (and the inverse — a
  reduction — for DEEP_WORKER), not just that the field is set.
- DEEP_WORKER separates from DOOMSCROLLER on category composition
  (near-opposite ends of the productive/addictive spectrum).
- generate_population() and build_population_spec() produce a
  correctly-shaped multi-user dataset.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.synthetic.archetypes import (
    ARCHETYPES,
    BALANCED,
    BINGE_WEEKEND,
    DEEP_WORKER,
    DOOMSCROLLER,
)
from attention_tracker.synthetic.generator import (
    SyntheticEventGenerator,
    build_population_spec,
    flatten_population,
)

# 2026-08-03 is a Monday, so this gives a clean two-week window with
# two full weekends inside it.
DAY_START = datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


class TestNewArchetypesRegistered:
    def test_all_four_archetypes_registered(self):
        assert set(ARCHETYPES.keys()) == {
            "BALANCED",
            "DOOMSCROLLER",
            "BINGE_WEEKEND",
            "DEEP_WORKER",
        }

    def test_binge_weekend_has_weekend_multipliers_above_one(self):
        assert BINGE_WEEKEND.weekend_session_multiplier > 1.0
        assert BINGE_WEEKEND.weekend_duration_multiplier > 1.0

    def test_deep_worker_has_weekend_multipliers_below_one(self):
        assert DEEP_WORKER.weekend_session_multiplier < 1.0
        assert DEEP_WORKER.weekend_duration_multiplier < 1.0

    def test_default_multipliers_are_neutral_for_existing_archetypes(self):
        # BALANCED and DOOMSCROLLER predate this field — confirm they
        # got the neutral default rather than silently changing
        # behavior when the field was added.
        assert BALANCED.weekend_session_multiplier == 1.0
        assert BALANCED.weekend_duration_multiplier == 1.0
        assert DOOMSCROLLER.weekend_session_multiplier == 1.0
        assert DOOMSCROLLER.weekend_duration_multiplier == 1.0


class TestNewArchetypeStructuralValidity:
    @pytest.mark.parametrize("profile", [BINGE_WEEKEND, DEEP_WORKER])
    def test_generates_valid_events(
        self, taxonomy: TaxonomyLoader, profile
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(1))
        events = gen.generate_day("user_test", profile, DAY_START)
        assert len(events) > 0
        assert all(isinstance(e, RawEvent) for e in events)
        for i in range(0, len(events), 2):
            assert events[i].event_type == EventType.OPENED
            assert events[i + 1].event_type == EventType.CLOSED


class TestWeekendMultiplierEffect:
    """DAY_START is a Monday; DAY_START + 5 days is Saturday. Generate
    both a weekday and a weekend day with the SAME rng seed reset each
    time, so any difference in output is attributable to the
    multiplier, not to RNG drift."""

    def test_binge_weekend_has_more_sessions_on_saturday_than_monday(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(99))
        weekday_events = gen.generate_day("u", BINGE_WEEKEND, DAY_START)

        gen2 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(99))
        saturday = DAY_START + timedelta(days=5)
        weekend_events = gen2.generate_day("u", BINGE_WEEKEND, saturday)

        weekday_sessions = len(weekday_events) // 2
        weekend_sessions = len(weekend_events) // 2
        assert weekend_sessions > weekday_sessions

    def test_binge_weekend_sessions_run_longer_on_saturday(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(99))
        weekday_events = gen.generate_day("u", BINGE_WEEKEND, DAY_START)

        gen2 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(99))
        saturday = DAY_START + timedelta(days=5)
        weekend_events = gen2.generate_day("u", BINGE_WEEKEND, saturday)

        def avg_duration(events):
            durations = [
                e.session_duration_sec
                for e in events
                if e.event_type == EventType.CLOSED
            ]
            return sum(durations) / len(durations)

        assert avg_duration(weekend_events) > avg_duration(weekday_events)

    def test_deep_worker_has_fewer_sessions_on_saturday_than_monday(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(55))
        weekday_events = gen.generate_day("u", DEEP_WORKER, DAY_START)

        gen2 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(55))
        saturday = DAY_START + timedelta(days=5)
        weekend_events = gen2.generate_day("u", DEEP_WORKER, saturday)

        weekday_sessions = len(weekday_events) // 2
        weekend_sessions = len(weekend_events) // 2
        assert weekend_sessions < weekday_sessions


class TestDeepWorkerVsDoomscrollerSeparation:
    """DEEP_WORKER and DOOMSCROLLER are designed as near-opposites on
    category composition. Confirm that separation actually holds in
    generated data, the same way Week 3 confirmed Balanced vs
    Doomscroller."""

    def _productive_time_fraction(
        self, events: list[RawEvent], taxonomy: TaxonomyLoader
    ) -> float:
        total = 0.0
        productive = 0.0
        for e in events:
            if e.event_type != EventType.CLOSED:
                continue
            total += e.session_duration_sec
            if taxonomy.lookup(e.package_name).category == AppCategory.PRODUCTIVE:
                productive += e.session_duration_sec
        return productive / total if total else 0.0

    def test_deep_worker_has_more_productive_time_than_doomscroller(
        self, taxonomy: TaxonomyLoader
    ):
        gen1 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(3))
        deep_worker_events = gen1.generate(
            "u_dw", DEEP_WORKER, DAY_START, num_days=14
        )

        gen2 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(3))
        doomscroller_events = gen2.generate(
            "u_doom", DOOMSCROLLER, DAY_START, num_days=14
        )

        dw_frac = self._productive_time_fraction(deep_worker_events, taxonomy)
        doom_frac = self._productive_time_fraction(doomscroller_events, taxonomy)
        assert dw_frac > doom_frac
        assert dw_frac - doom_frac > 0.3

    def test_deep_worker_has_fewer_sessions_per_day_than_doomscroller(
        self, taxonomy: TaxonomyLoader
    ):
        gen1 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(3))
        deep_worker_events = gen1.generate(
            "u_dw", DEEP_WORKER, DAY_START, num_days=14
        )

        gen2 = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(3))
        doomscroller_events = gen2.generate(
            "u_doom", DOOMSCROLLER, DAY_START, num_days=14
        )

        dw_sessions = len(deep_worker_events) // 2
        doom_sessions = len(doomscroller_events) // 2
        assert dw_sessions < doom_sessions


class TestPopulationGeneration:
    def test_build_population_spec_produces_correct_counts(self):
        spec = build_population_spec(
            [(BALANCED, 3), (DOOMSCROLLER, 2), (BINGE_WEEKEND, 1), (DEEP_WORKER, 1)]
        )
        assert len(spec) == 7
        assert sum(1 for p in spec.values() if p is BALANCED) == 3
        assert sum(1 for p in spec.values() if p is DOOMSCROLLER) == 2

    def test_population_user_ids_embed_archetype_name(self):
        spec = build_population_spec([(BALANCED, 2)])
        assert set(spec.keys()) == {"user_BALANCED_000", "user_BALANCED_001"}

    def test_generate_population_returns_per_user_events(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(11))
        spec = build_population_spec([(BALANCED, 2), (DOOMSCROLLER, 2)])
        result = gen.generate_population(spec, DAY_START, num_days=3)

        assert set(result.keys()) == set(spec.keys())
        for user_id, events in result.items():
            assert len(events) > 0
            assert all(e.user_id == user_id for e in events)

    def test_flatten_population_merges_and_sorts_chronologically(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(11))
        spec = build_population_spec([(BALANCED, 2), (DOOMSCROLLER, 2)])
        result = gen.generate_population(spec, DAY_START, num_days=3)

        flat = flatten_population(result)
        total_individual = sum(len(events) for events in result.values())
        assert len(flat) == total_individual

        timestamps = [e.timestamp for e in flat]
        assert timestamps == sorted(timestamps)

    def test_population_of_mixed_archetypes_end_to_end(
        self, taxonomy: TaxonomyLoader
    ):
        """A realistic Month-4-scale dataset: uneven archetype mix,
        two weeks of data, confirming nothing breaks at that scale
        and every event is independently valid."""
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(2026))
        spec = build_population_spec(
            [(BALANCED, 10), (DOOMSCROLLER, 8), (BINGE_WEEKEND, 5), (DEEP_WORKER, 5)]
        )
        result = gen.generate_population(spec, DAY_START, num_days=14)
        flat = flatten_population(result)

        assert len(result) == 28
        assert len(flat) > 0
        assert all(isinstance(e, RawEvent) for e in flat)