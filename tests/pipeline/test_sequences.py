import math
from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.pipeline.sequences import (
    CATEGORY_ORDER,
    MAX_GAP_SEC,
    STEP_DIM,
    STEP_FEATURE_NAMES,
    build_day_sequences,
)
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

T0 = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)  # a Wednesday


@pytest.fixture(scope="module")
def tax():
    return TaxonomyLoader()


def sess(pkg, start_offset_s, dur_s, sid, user="u1", tz=0, base=T0):
    start = base + timedelta(seconds=start_offset_s)
    return Session(
        user_id=user, package_name=pkg, session_id=sid,
        start_time=start, end_time=start + timedelta(seconds=dur_s),
        duration_sec=float(dur_s), tz_offset_minutes=tz,
    )


def col(name):
    return STEP_FEATURE_NAMES.index(name)


class TestShape:
    def test_step_dim_matches_feature_names(self):
        assert STEP_DIM == len(STEP_FEATURE_NAMES) == 6 + len(CATEGORY_ORDER)

    def test_every_step_vector_has_step_dim_columns(self, tax):
        (seq,) = build_day_sequences([sess("com.whatsapp", 0, 60, "a")], tax, max_len=4)
        assert all(len(step) == STEP_DIM for step in seq.steps)
        assert len(seq.steps) == 4

    def test_empty_input_gives_no_sequences(self, tax):
        assert build_day_sequences([], tax) == []

    def test_max_len_below_one_rejected(self, tax):
        with pytest.raises(ValueError):
            build_day_sequences([], tax, max_len=0)


class TestOrderingAndGrouping:
    def test_sessions_are_ordered_by_start_time_regardless_of_input_order(self, tax):
        a = sess("com.whatsapp", 0, 60, "a")
        b = sess("com.instagram.android", 300, 60, "b")
        (seq,) = build_day_sequences([b, a], tax, max_len=4)
        # First real step is the WhatsApp session (COMMUNICATION),
        # second is Instagram (ADDICTIVE).
        comm = col("cat_communication")
        addictive = col("cat_addictive")
        assert seq.steps[0][comm] == 1.0
        assert seq.steps[1][addictive] == 1.0

    def test_one_sequence_per_user_day(self, tax):
        day2 = T0 + timedelta(days=1)
        sessions = [
            sess("com.whatsapp", 0, 60, "a"),
            sess("com.whatsapp", 0, 60, "b", base=day2),
            sess("com.whatsapp", 0, 60, "c", user="u2"),
        ]
        seqs = build_day_sequences(sessions, tax)
        assert [(s.user_id, s.day.day) for s in seqs] == [("u1", 5), ("u1", 6), ("u2", 5)]

    def test_local_day_not_utc_day_decides_grouping(self, tax):
        # 20:30 UTC on Aug 5 is 02:00 IST on Aug 6.
        late = datetime(2026, 8, 5, 20, 30, tzinfo=timezone.utc)
        (seq,) = build_day_sequences(
            [sess("com.whatsapp", 0, 60, "a", tz=330, base=late)], tax
        )
        assert seq.day.day == 6


class TestStepFeatures:
    def test_duration_is_log1p(self, tax):
        (seq,) = build_day_sequences([sess("com.whatsapp", 0, 120, "a")], tax, max_len=2)
        assert seq.steps[0][col("log1p_duration_sec")] == pytest.approx(math.log1p(120))

    def test_first_session_of_day_gets_the_capped_gap(self, tax):
        (seq,) = build_day_sequences([sess("com.whatsapp", 0, 60, "a")], tax, max_len=2)
        assert seq.steps[0][col("log1p_gap_since_prev_sec")] == pytest.approx(
            math.log1p(MAX_GAP_SEC)
        )

    def test_gap_is_measured_from_previous_end_to_next_start(self, tax):
        a = sess("com.whatsapp", 0, 60, "a")  # ends at +60
        b = sess("com.whatsapp", 100, 30, "b")  # gap = 40
        (seq,) = build_day_sequences([a, b], tax, max_len=2)
        assert seq.steps[1][col("log1p_gap_since_prev_sec")] == pytest.approx(math.log1p(40))

    def test_long_gap_is_clipped(self, tax):
        a = sess("com.whatsapp", 0, 60, "a")
        b = sess("com.whatsapp", 60 + 10 * 3600, 30, "b")  # 10h gap
        (seq,) = build_day_sequences([a, b], tax, max_len=2)
        assert seq.steps[1][col("log1p_gap_since_prev_sec")] == pytest.approx(
            math.log1p(MAX_GAP_SEC)
        )

    def test_app_switch_flag(self, tax):
        a = sess("com.whatsapp", 0, 60, "a")
        b = sess("com.instagram.android", 100, 60, "b")
        c = sess("com.instagram.android", 200, 60, "c")
        (seq,) = build_day_sequences([a, b, c], tax, max_len=4)
        sw = col("is_app_switch")
        assert [seq.steps[i][sw] for i in range(3)] == [0.0, 1.0, 0.0]

    def test_hour_encoding_is_cyclic(self, tax):
        # 23:30 and 00:30 local are one hour apart; their (sin, cos)
        # points must be closer than 23:30 and 12:00.
        def point(hour, minute):
            base = datetime(2026, 8, 5, hour, minute, tzinfo=timezone.utc)
            (seq,) = build_day_sequences(
                [sess("com.whatsapp", 0, 60, "a", base=base)], tax, max_len=1
            )
            return seq.steps[0][col("hour_sin")], seq.steps[0][col("hour_cos")]

        def dist(p, q):
            return math.dist(p, q)

        assert dist(point(23, 30), point(0, 30)) < dist(point(23, 30), point(12, 0))

    def test_weekend_flag(self, tax):
        sat = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        (weekday,) = build_day_sequences([sess("com.whatsapp", 0, 60, "a")], tax, max_len=1)
        (weekend,) = build_day_sequences(
            [sess("com.whatsapp", 0, 60, "b", base=sat)], tax, max_len=1
        )
        assert weekday.steps[0][col("is_weekend")] == 0.0
        assert weekend.steps[0][col("is_weekend")] == 1.0

    def test_category_one_hot_has_exactly_one_hot(self, tax):
        (seq,) = build_day_sequences(
            [sess("com.some.unknown.app", 0, 60, "a")], tax, max_len=1
        )
        cat_cols = [col(f"cat_{c.value.lower()}") for c in CATEGORY_ORDER]
        values = [seq.steps[0][i] for i in cat_cols]
        assert sum(values) == 1.0
        assert seq.steps[0][col("cat_unknown")] == 1.0


class TestPaddingAndTruncation:
    def test_padding_is_zero_and_masked(self, tax):
        (seq,) = build_day_sequences([sess("com.whatsapp", 0, 60, "a")], tax, max_len=4)
        assert seq.mask == [1, 0, 0, 0]
        assert seq.length == 1
        assert seq.truncated_steps == 0
        assert all(v == 0.0 for step in seq.steps[1:] for v in step)

    def test_truncation_keeps_the_last_steps_and_reports_the_drop(self, tax):
        sessions = [sess("com.whatsapp", i * 100, 30, f"s{i}") for i in range(6)]
        (seq,) = build_day_sequences(sessions, tax, max_len=4)
        assert seq.length == 4
        assert seq.truncated_steps == 2
        assert seq.mask == [1, 1, 1, 1]
        # Kept steps are sessions 2..5, so the last one's gap is 70s.
        assert seq.steps[-1][col("log1p_gap_since_prev_sec")] == pytest.approx(math.log1p(70))

    def test_mask_sum_equals_length(self, tax):
        sessions = [sess("com.whatsapp", i * 100, 30, f"s{i}") for i in range(3)]
        (seq,) = build_day_sequences(sessions, tax, max_len=8)
        assert sum(seq.mask) == seq.length == 3