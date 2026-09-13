from datetime import datetime, timedelta, timezone

import pytest

from attention_tracker.pipeline.features.feature_vector import (
    FeatureVector,
    build_feature_vector,
)
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

T0 = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def taxonomy() -> TaxonomyLoader:
    return TaxonomyLoader()


def make_session(start, duration_sec, session_id, transition_from=None):
    return Session(
        user_id="u1",
        package_name="com.instagram.android",
        session_id=session_id,
        start_time=start,
        end_time=start + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
        transition_from=transition_from,
    )


class TestBuildFeatureVector:
    def test_empty_list_raises(self, taxonomy):
        with pytest.raises(ValueError, match="at least one session"):
            build_feature_vector([], taxonomy)

    def test_returns_feature_vector_with_correct_identity_fields(self, taxonomy):
        sessions = [make_session(T0, 60.0, "s1")]
        fv = build_feature_vector(sessions, taxonomy)
        assert isinstance(fv, FeatureVector)
        assert fv.user_id == "u1"
        assert fv.package_name == "com.instagram.android"

    def test_single_session_leaves_interarrival_fields_none(self, taxonomy):
        # interarrival_mean_sec / interarrival_under_2min_ratio need
        # 2+ sessions — a single-session group must not raise, and
        # must surface None rather than a fabricated value.
        sessions = [make_session(T0, 60.0, "s1")]
        fv = build_feature_vector(sessions, taxonomy)
        assert fv.interarrival_mean_sec is None
        assert fv.interarrival_under_2min_ratio is None

    def test_multi_session_populates_interarrival_fields(self, taxonomy):
        sessions = [
            make_session(T0, 60.0, "s1"),
            make_session(T0 + timedelta(minutes=5), 60.0, "s2"),
        ]
        fv = build_feature_vector(sessions, taxonomy)
        assert fv.interarrival_mean_sec is not None
        assert fv.interarrival_under_2min_ratio is not None

    def test_all_volume_fields_populated_correctly(self, taxonomy):
        sessions = [
            make_session(T0, 60.0, "s1"),
            make_session(T0 + timedelta(minutes=5), 120.0, "s2"),
        ]
        fv = build_feature_vector(sessions, taxonomy)
        assert fv.total_time_sec == 180.0
        assert fv.session_count == 2
        assert fv.avg_session_duration_sec == 90.0
        assert fv.max_session_duration_sec == 120.0

    def test_temporal_fields_are_populated(self, taxonomy):
        sessions = [make_session(T0, 60.0, "s1")]
        fv = build_feature_vector(sessions, taxonomy)
        assert 0.0 <= fv.late_night_usage_pct <= 1.0
        assert 0.0 <= fv.hourly_usage_entropy <= 1.0
        assert 0.0 <= fv.weekend_usage_ratio <= 1.0

    def test_transition_field_is_populated(self, taxonomy):
        sessions = [
            make_session(T0, 60.0, "s1", transition_from="com.google.android.apps.docs")
        ]
        fv = build_feature_vector(sessions, taxonomy)
        assert fv.productive_interruption_rate == 1.0

    def test_feature_vector_is_frozen(self, taxonomy):
        sessions = [make_session(T0, 60.0, "s1")]
        fv = build_feature_vector(sessions, taxonomy)
        with pytest.raises(Exception):
            fv.total_time_sec = 999.0