from datetime import datetime, timezone

import pytest

from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.app_metadata_entry import AppMetadataEntry
from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.storage.db import Database
from attention_tracker.storage.repository import DailyRow, Repository, WindowRow
from attention_tracker.synthetic.archetypes import ARCHETYPES
from attention_tracker.synthetic.generator import SyntheticEventGenerator

TAXONOMY = TaxonomyLoader()


@pytest.fixture
def repo():
    return Repository(Database(":memory:"))


@pytest.fixture(scope="module")
def events():
    day = datetime(2026, 3, 2, tzinfo=timezone.utc)
    return SyntheticEventGenerator().generate("u1", ARCHETYPES["DOOMSCROLLER"], day, num_days=2)


def _open(ts_minute: int) -> RawEvent:
    return RawEvent(
        user_id="u1",
        package_name="com.x",
        event_type=EventType.OPENED,
        timestamp=datetime(2026, 3, 2, 10, ts_minute, tzinfo=timezone.utc),
        tz_offset_minutes=330,
    )


def test_create_user_is_idempotent(repo):
    assert repo.create_user("u1") is True
    assert repo.create_user("u1") is False
    assert repo.get_user("u1")["consent_at"] is None


def test_consent_first_time_wins(repo):
    repo.create_user("u1")
    first = repo.set_consent("u1")
    assert first is not None
    assert repo.set_consent("u1") == first
    assert repo.set_consent("ghost") is None


def test_insert_events_counts_and_is_idempotent(repo, events):
    repo.create_user("u1")
    accepted, dup = repo.insert_events("u1", events)
    assert (accepted, dup) == (len(events), 0)

    accepted, dup = repo.insert_events("u1", events)
    assert (accepted, dup) == (0, len(events))


def test_events_round_trip_through_the_database(repo, events):
    repo.create_user("u1")
    repo.insert_events("u1", events)
    loaded = repo.load_events("u1")

    assert len(loaded) == len(events)
    key = lambda e: (e.timestamp, e.package_name, e.event_type.value)  # noqa: E731
    assert sorted(loaded, key=key) == sorted(events, key=key)


def test_insert_marks_scores_stale_only_when_something_was_accepted(repo):
    repo.create_user("u1")
    repo.insert_events("u1", [_open(1)])
    repo.replace_derived("u1", [], [], [])
    assert repo.get_user("u1")["scores_stale"] == 0

    repo.insert_events("u1", [_open(1)])  # pure duplicate
    assert repo.get_user("u1")["scores_stale"] == 0
    repo.insert_events("u1", [_open(2)])
    assert repo.get_user("u1")["scores_stale"] == 1


def test_events_for_unknown_user_are_rejected_by_fk(repo):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_events("ghost", [_open(1)])


def _derive(repo, events):
    result = run_data_quality_pipeline(events, taxonomy=TAXONOMY)
    windows = []
    for (_u, _pkg, day), sessions in group_sessions_by_user_app_day(result.sessions).items():
        fv = build_feature_vector(sessions, TAXONOMY)
        windows.append(
            WindowRow(
                day=day,
                features=fv,
                category=TAXONOMY.lookup(fv.package_name).category,
                heuristic_score=5.0,
                distraction_score=4.0,
                addiction_model_score=6.0,
                addiction_model_version="v1",
            )
        )
    days = sorted({w.day for w in windows})
    daily = [DailyRow(d, 100.0, 5.0, 4.0, 6.0, None, True, 1.0, "ok") for d in days]
    return result.sessions, windows, daily


def test_replace_derived_stores_and_rebuilds(repo, events):
    repo.create_user("u1")
    sessions, windows, daily = _derive(repo, events)

    repo.replace_derived("u1", sessions, windows, daily)
    assert len(repo.list_window_scores("u1")) == len(windows)
    assert len(repo.list_daily_scores("u1")) == len(daily)

    # Rebuilding replaces, never duplicates.
    repo.replace_derived("u1", sessions, windows, daily)
    assert len(repo.list_window_scores("u1")) == len(windows)
    assert repo.get_user("u1")["scores_stale"] == 0
    assert repo.get_user("u1")["last_scored_at"] is not None


def test_none_features_are_stored_as_null_not_zero(repo, events):
    repo.create_user("u1")
    sessions, windows, daily = _derive(repo, events)
    one_session = [w for w in windows if w.features.session_count == 1]
    assert one_session, "synthetic data should contain a one-session window"
    repo.replace_derived("u1", sessions, windows, daily)
    row = repo.db.conn.execute(
        "SELECT interarrival_mean_sec FROM feature_vectors WHERE user_id='u1' AND package_name=? AND day=?",
        (one_session[0].features.package_name, one_session[0].day.isoformat()),
    ).fetchone()
    assert row["interarrival_mean_sec"] is None


def test_score_listing_filters_by_date(repo, events):
    repo.create_user("u1")
    sessions, windows, daily = _derive(repo, events)
    repo.replace_derived("u1", sessions, windows, daily)
    days = sorted({w.day for w in windows})
    assert len(days) >= 2

    only_first = repo.list_window_scores("u1", start=days[0], end=days[0])
    assert {r["day"] for r in only_first} == {days[0].isoformat()}
    assert [d["day"] for d in repo.list_daily_scores("u1", start=days[1])] == [d.isoformat() for d in days[1:]]


def test_delete_user_removes_every_row(repo, events):
    repo.create_user("u1")
    repo.create_device("d1", "u1", "hash1")
    repo.insert_events("u1", events)
    sessions, windows, daily = _derive(repo, events)
    repo.replace_derived("u1", sessions, windows, daily)
    repo.upsert_sas_sv_total("u1", 30)
    repo.create_user("u2")
    repo.insert_events("u2", [_open(1).model_copy(update={"user_id": "u2"})])

    assert repo.delete_user("u1") is True
    assert repo.delete_user("u1") is False

    for table in ("devices", "raw_events", "sessions", "feature_vectors", "scores", "daily_scores", "sas_sv_labels"):
        n = repo.db.conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = 'u1'").fetchone()["n"]
        assert n == 0, table
    assert len(repo.load_events("u2")) == 1  # other users untouched


def test_device_token_lookup_and_revocation(repo):
    repo.create_user("u1")
    repo.create_device("d1", "u1", "hash1")
    assert repo.device_for_token_hash("hash1") == {"device_id": "d1", "user_id": "u1"}
    assert repo.device_for_token_hash("nope") is None
    assert repo.revoke_device("d1") is True
    assert repo.revoke_device("d1") is False
    assert repo.device_for_token_hash("hash1") is None


def test_sas_sv_upsert_keeps_latest_total_only(repo):
    repo.create_user("u1")
    repo.upsert_sas_sv_total("u1", 25)
    repo.upsert_sas_sv_total("u1", 41)
    assert repo.get_sas_sv("u1")["sas_sv_total"] == 41


def test_seed_app_metadata_never_overwrites_an_override(repo):
    repo.seed_app_metadata([AppMetadataEntry(package_name="com.x", display_name="X", category=AppCategory.ADDICTIVE)])
    with repo.db.transaction() as c:
        c.execute("UPDATE app_metadata SET category='PRODUCTIVE', is_user_override=1 WHERE package_name='com.x'")
    repo.seed_app_metadata([AppMetadataEntry(package_name="com.x", display_name="X", category=AppCategory.ADDICTIVE)])

    assert repo.category_override("com.x") == AppCategory.PRODUCTIVE
    assert repo.category_override("com.unknown") is None


def test_export_contains_user_data_but_not_token_hashes(repo, events):
    repo.create_user("u1")
    repo.create_device("d1", "u1", "secret-hash")
    repo.insert_events("u1", events)
    repo.upsert_sas_sv_total("u1", 30)

    dump = repo.export_user("u1")
    assert dump["user"]["user_id"] == "u1"
    assert len(dump["raw_events"]) == len(events)
    assert dump["sas_sv_label"]["sas_sv_total"] == 30
    assert "secret-hash" not in repr(dump)
    assert repo.export_user("ghost") is None
