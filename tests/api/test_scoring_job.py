import pytest

from attention_tracker.api.scoring_job import ModelCache, ScoringJob
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.app_metadata_entry import AppMetadataEntry
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.storage.db import Database
from attention_tracker.storage.repository import Repository

TAXONOMY = TaxonomyLoader(include_extended=True)


@pytest.fixture
def repo():
    r = Repository(Database(":memory:"))
    r.create_user("u1")
    return r


@pytest.fixture
def job(repo, tmp_path):
    # empty model dir -> heuristic-only scoring
    return ScoringJob(repo, TAXONOMY, ModelCache(tmp_path / "no_models"))


def test_scoring_populates_all_derived_tables(repo, job, make_events):
    events = make_events("u1")
    repo.insert_events("u1", events)

    summary = job.score_user("u1")

    assert summary.sessions > 0 and summary.windows > 0 and summary.days >= 2
    assert len(repo.list_window_scores("u1")) == summary.windows
    assert len(repo.list_daily_scores("u1")) == summary.days
    assert repo.get_user("u1")["scores_stale"] == 0


def test_heuristic_only_when_no_model_in_registry(repo, job, make_events):
    repo.insert_events("u1", make_events("u1"))
    job.score_user("u1")

    row = repo.list_window_scores("u1")[0]
    assert 0.0 <= row["heuristic_score"] <= 10.0
    assert 0.0 <= row["distraction_score"] <= 10.0
    assert row["addiction_model_score"] is None
    assert row["addiction_model_version"] is None
    assert all(d["addiction_model_score"] is None for d in repo.list_daily_scores("u1"))


def test_scores_match_direct_pipeline_computation(repo, job, make_events):
    """The stored heuristic score must equal what the unchanged pipeline computes."""
    from attention_tracker.pipeline.features.feature_vector import build_feature_vector
    from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
    from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
    from attention_tracker.scoring.heuristic import compute_heuristic_score

    events = make_events("u1")
    repo.insert_events("u1", events)
    job.score_user("u1")

    result = run_data_quality_pipeline(events, taxonomy=TAXONOMY)
    expected = {}
    for (_u, pkg, day), group in group_sessions_by_user_app_day(result.sessions).items():
        fv = build_feature_vector(group, TAXONOMY)
        expected[(pkg, day.isoformat())] = compute_heuristic_score(fv, TAXONOMY.lookup(pkg).category)

    stored = {(r["package_name"], r["day"]): r["heuristic_score"] for r in repo.list_window_scores("u1")}
    assert stored.keys() == expected.keys()
    for k, v in expected.items():
        assert stored[k] == pytest.approx(v)


def test_daily_score_is_time_weighted_mean_of_app_scores(repo, job, make_events):
    repo.insert_events("u1", make_events("u1"))
    job.score_user("u1")

    day = repo.list_daily_scores("u1")[0]["day"]
    apps = [r for r in repo.list_window_scores("u1") if r["day"] == day]
    total = sum(r["total_time_sec"] for r in apps)
    expected = sum(r["heuristic_score"] * r["total_time_sec"] for r in apps) / total
    assert repo.list_daily_scores("u1")[0]["heuristic_score"] == pytest.approx(expected)
    assert repo.list_daily_scores("u1")[0]["total_time_sec"] == pytest.approx(total)


def test_rescoring_is_deterministic(repo, job, make_events):
    repo.insert_events("u1", make_events("u1"))
    job.score_user("u1")
    first = repo.list_daily_scores("u1")
    job.score_user("u1")
    assert repo.list_daily_scores("u1") == first


def test_user_with_no_events_scores_to_nothing(repo, job):
    summary = job.score_user("u1")
    assert (summary.sessions, summary.windows, summary.days) == (0, 0, 0)
    assert repo.get_user("u1")["scores_stale"] == 0


def test_ensure_scored_only_runs_when_stale(repo, job, make_events):
    assert job.ensure_scored("ghost") is False
    repo.insert_events("u1", make_events("u1"))
    assert job.ensure_scored("u1") is True
    assert job.ensure_scored("u1") is False
    repo.insert_events("u1", make_events("u1", num_days=3))  # adds a new day
    assert job.ensure_scored("u1") is True
    assert len(repo.list_daily_scores("u1")) >= 3


def test_score_stale_users_skips_fresh_ones(repo, job, make_events):
    repo.create_user("u2")
    repo.insert_events("u1", make_events("u1"))
    out = job.score_stale_users()
    assert {s.user_id for s in out} == {"u1", "u2"}
    assert job.score_stale_users() == []


def test_user_category_override_changes_the_score(repo, job, make_events):
    repo.insert_events("u1", make_events("u1"))
    job.score_user("u1")
    top = repo.list_window_scores("u1")[0]
    pkg = top["package_name"]
    before = {(r["package_name"], r["day"]): r["heuristic_score"] for r in repo.list_window_scores("u1")}

    repo.seed_app_metadata([AppMetadataEntry(package_name=pkg, display_name=pkg, category=AppCategory.ADDICTIVE)])
    with repo.db.transaction() as c:
        c.execute(
            "UPDATE app_metadata SET category='PRODUCTIVE', is_user_override=1 WHERE package_name=?", (pkg,)
        )
    job.score_user("u1")

    after = {(r["package_name"], r["day"]): r["heuristic_score"] for r in repo.list_window_scores("u1")}
    changed = [k for k in before if k[0] == pkg and after[k] != before[k]]
    assert changed and all(after[k] < before[k] for k in changed)


def test_ignored_system_packages_are_not_scored(repo, job, make_events):
    from datetime import datetime, timezone

    from attention_tracker.schema.raw_event import EventType, RawEvent

    ignored = sorted(TAXONOMY._ignored)[0]
    t0 = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 3, 2, 9, 5, tzinfo=timezone.utc)
    repo.insert_events(
        "u1",
        [
            RawEvent(user_id="u1", package_name=ignored, event_type=EventType.OPENED, timestamp=t0, tz_offset_minutes=0),
            RawEvent(
                user_id="u1",
                package_name=ignored,
                event_type=EventType.CLOSED,
                timestamp=t1,
                tz_offset_minutes=0,
                session_duration_sec=300,
                session_id="s-ignored",
            ),
        ],
    )
    job.score_user("u1")
    assert repo.list_window_scores("u1") == []
