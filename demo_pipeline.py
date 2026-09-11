from datetime import datetime, timezone

from attention_tracker.pipeline.features.compulsiveness import (
    interarrival_mean_sec,
    sessions_under_30s_ratio,
)
from attention_tracker.pipeline.features.volume import (
    avg_session_duration_sec,
    max_session_duration_sec,
    session_count,
    total_time_sec,
)
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.synthetic.archetypes import ARCHETYPES
from attention_tracker.synthetic.generator import (
    SyntheticEventGenerator,
    build_population_spec,
)

START_DATE = datetime(2026, 8, 3, tzinfo=timezone.utc)
NUM_DAYS = 7


def run():
    print("=" * 70)
    print("ATTENTION ECONOMY TRACKER — end-to-end pipeline demo")
    print("=" * 70)

    # --- Stage 1: synthetic data generation (M2) ---
    gen = SyntheticEventGenerator()
    spec = build_population_spec(
        [(profile, 1) for profile in ARCHETYPES.values()]
    )
    population_events = gen.generate_population(spec, START_DATE, NUM_DAYS)
    all_events = [e for events in population_events.values() for e in events]

    print(f"\n[1] Generated {len(all_events)} raw events across "
          f"{len(spec)} synthetic users ({NUM_DAYS} days each)")
    for archetype_name in ARCHETYPES:
        print(f"      - {archetype_name}")

    # --- Stages 2-4: dedup -> session building -> outlier capping,
    # run as a single orchestrated data-quality pipeline stage
    # (previously these existed as separate, unwired functions) ---
    quality_result = run_data_quality_pipeline(all_events)
    print(f"\n[2] Dedup: {quality_result.dedup_result.duplicate_count} "
          f"duplicates removed (0 expected — synthetic data has no retries "
          f"by construction)")
    print(f"\n[3] Session building: {len(quality_result.build_result.sessions)} "
          f"sessions built, "
          f"{len(quality_result.build_result.unmatched_opens)} unmatched opens, "
          f"{len(quality_result.build_result.unmatched_closes)} unmatched closes")
    print(f"\n[4] Outlier capping: {quality_result.outlier_result.capped_count} "
          f"sessions capped (0 expected — synthetic generator doesn't produce "
          f"wake-lock-style artifacts)")

    # --- Stage 5: windowing (group by user, app, day) ---
    windows = group_sessions_by_user_app_day(quality_result.sessions)
    print(f"\n[5] Windowing: {len(windows)} (user, app, day) groups")

    # --- Stage 6: feature computation (M3) ---
    print(f"\n[6] Sample computed features (first 5 windows with 2+ sessions):")
    print("-" * 70)
    shown = 0
    for (user_id, package_name, day), sessions in windows.items():
        if len(sessions) < 2:
            continue  # interarrival features need at least 2 sessions
        shown += 1
        print(f"\n  user={user_id}  app={package_name}  day={day}")
        print(f"    session_count               = {session_count(sessions)}")
        print(f"    total_time_sec              = {total_time_sec(sessions):.1f}")
        print(f"    avg_session_duration_sec    = {avg_session_duration_sec(sessions):.1f}")
        print(f"    max_session_duration_sec    = {max_session_duration_sec(sessions):.1f}")
        print(f"    interarrival_mean_sec       = {interarrival_mean_sec(sessions):.1f}")
        print(f"    sessions_under_30s_ratio    = {sessions_under_30s_ratio(sessions):.2f}")
        if shown >= 5:
            break

    print("\n" + "=" * 70)
    print("Pipeline run complete.")
    print("=" * 70)


if __name__ == "__main__":
    run()