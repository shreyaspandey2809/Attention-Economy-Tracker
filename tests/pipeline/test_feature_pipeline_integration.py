import random
from datetime import datetime, timezone

import pytest

from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.synthetic.archetypes import BALANCED, DOOMSCROLLER
from attention_tracker.synthetic.generator import (
    SyntheticEventGenerator,
    build_population_spec,
    flatten_population,
)
from attention_tracker.pipeline.session_builder import SessionBuilder
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.pipeline.features.volume import (
    session_count,
    total_time_sec,
)
from attention_tracker.pipeline.features.compulsiveness import (
    interarrival_mean_sec,
    sessions_under_30s_ratio,
)

DAY_START = datetime(2026, 8, 3, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


class TestFullPipelineToFeatures:
    def test_volume_features_computable_for_every_group(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(2026))
        events = gen.generate("user_bal", BALANCED, DAY_START, num_days=14)
        result = SessionBuilder().build(events)
        groups = group_sessions_by_user_app_day(result.sessions)

        assert len(groups) > 0
        for key, sessions in groups.items():
            # Every group has at least one session by construction —
            # volume features should never raise here.
            assert total_time_sec(sessions) > 0
            assert session_count(sessions) == len(sessions)

    def test_compulsiveness_features_computable_where_applicable(
        self, taxonomy: TaxonomyLoader
    ):
        gen = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(2026))
        events = gen.generate("user_doom", DOOMSCROLLER, DAY_START, num_days=14)
        result = SessionBuilder().build(events)
        groups = group_sessions_by_user_app_day(result.sessions)

        multi_session_groups = [g for g in groups.values() if len(g) >= 2]
        assert len(multi_session_groups) > 0, (
            "expected at least one (user, app, day) group with 2+ sessions "
            "over a 14-day Doomscroller window"
        )

        for sessions in multi_session_groups:
            gap = interarrival_mean_sec(sessions)
            assert gap >= 0  # non-overlap guarantee means gaps can't be negative
            ratio = sessions_under_30s_ratio(sessions)
            assert 0.0 <= ratio <= 1.0

    def test_doomscroller_has_higher_quick_return_rate_than_balanced(
        self, taxonomy: TaxonomyLoader
    ):

        def pooled_quick_return_ratio(events) -> float:
            result = SessionBuilder().build(events)
            groups = group_sessions_by_user_app_day(result.sessions)
            all_gaps: list[float] = []
            for sessions in groups.values():
                if len(sessions) < 2:
                    continue
                all_gaps.extend(
                    (sessions[i].start_time - sessions[i - 1].end_time).total_seconds()
                    for i in range(1, len(sessions))
                )
            quick = sum(1 for g in all_gaps if g < 120.0)
            return quick / len(all_gaps) if all_gaps else 0.0

        gen_bal = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(5))
        spec_bal = build_population_spec([(BALANCED, 15)], user_id_prefix="bal")
        bal_events = flatten_population(
            gen_bal.generate_population(spec_bal, DAY_START, num_days=14)
        )

        gen_doom = SyntheticEventGenerator(taxonomy=taxonomy, rng=random.Random(5))
        spec_doom = build_population_spec([(DOOMSCROLLER, 15)], user_id_prefix="doom")
        doom_events = flatten_population(
            gen_doom.generate_population(spec_doom, DAY_START, num_days=14)
        )

        bal_ratio = pooled_quick_return_ratio(bal_events)
        doom_ratio = pooled_quick_return_ratio(doom_events)

        assert doom_ratio > bal_ratio