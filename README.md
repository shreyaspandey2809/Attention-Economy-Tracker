# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See [`docs/architecture.md`](docs/architecture.md) for the full module
map and data-flow diagram. Build runs in four phases:

- **Phase 1 — Data foundation:** schema, synthetic data generation,
  session joining, feature engineering, heuristic baseline (M1-M4)
- **Phase 2 — ML core:** LightGBM addiction + distraction models,
  LSTM sequence model, autoencoder, SHAP explainability (M5-M7)
- **Phase 3 — Backend + database:** SQLite storage, FastAPI serving
  layer, config migration (M8)
- **Phase 4 — Android + frontend:** on-device collector, React
  dashboard (M9-M10)

## Status: Phase 1 — Data Foundation (M3 complete)

- [x] M1: Schema Layer — `RawEvent`, `Session`, `AppMetadataEntry`,
      `TaxonomyLoader` + 50-app seed taxonomy
- [x] M2: Synthetic Data Generator — all 5 archetypes (`BALANCED`,
      `DOOMSCROLLER`, `BINGE_WEEKEND`, `DEEP_WORKER`,
      `COMPULSIVE_CHECKER`) + population generation
- [x] M3: `SessionBuilder` — joins OPENED/CLOSED event pairs into
      `Session` records via FIFO pairing per (user, package), with
      `transition_from` / `transition_to` from each user's
      chronological session order
- [x] **Bugfix found during Session Builder testing:** the synthetic
      generator (M2) could produce overlapping sessions — physically
      impossible on a real device (only one app can be in the
      foreground at a time). Fixed by clamping start times against a
      running cursor, threaded across day boundaries. Verified with a
      200-seed × 4-archetype × 30-day stress check (427,739
      adjacent-session pairs, zero overlaps).
- [x] **Weakness found during review: archetype coverage gap.** The
      project synopsis commits to "at least five" behavioral
      archetypes and names Compulsive Checker explicitly; only four
      were implemented. Added `COMPULSIVE_CHECKER` (very high session
      count, each session short) to close the gap, validated against
      Doomscroller (longer, less frequent sessions) at scale.
- [x] Data-quality stage (State-and-Plan Sec. 2) — added after
      discovering it needed to exist *before* Temporal/Transition
      features, since noisy or duplicate input would corrupt every
      feature computed on top of it:
  - `pipeline/quality/dedup.py` — removes duplicate `RawEvent`s using
    `session_id` as an idempotency key for terminal events, and exact
    `(user_id, package_name, timestamp)` matching for OPENED events
    lacking one (e.g. a WorkManager sync retry)
  - `pipeline/quality/outliers.py` — caps session durations at a
    device-plausibility bound (4 hours), not a statistical
    percentile, so genuine heavy-usage days (Doomscroller,
    Binge Weekend) aren't clipped alongside measurement errors (e.g.
    a stale wake-lock producing a 14-hour "session")
  - `pipeline/quality/pipeline.py` — orchestrates dedup → session
    building → outlier capping as one callable stage, so the fix
    actually runs in the pipeline rather than existing only as
    independently-tested modules
  - Missing-data/completeness flagging (Sec. 2.3) is the one deferred
    piece — it depends on an Android sync-heartbeat signal that
    doesn't exist until M9
- [x] M3: `windowing.py` — groups sessions by (user, app, calendar
      day), pre-sorted by start_time, as the shared grouping every
      feature function builds on
- [x] M3: Volume features (`volume.py`) — `total_time_sec`,
      `session_count`, `avg_session_duration_sec`,
      `max_session_duration_sec`
- [x] M3: Compulsiveness features (`compulsiveness.py`) —
      `interarrival_mean_sec`, `sessions_under_30s_ratio`,
      `interarrival_under_2min_ratio`
- [x] **Test-design finding:** an early integration test asserted
      Doomscroller shows a shorter average same-app return gap than
      Balanced, computed as an unweighted mean of per-(user, app,
      day)-group means. That statistic was genuinely unreliable — most
      groups have only 2 sessions, so a single wide within-day gap
      swings a group's mean by hours and a few noisy small groups
      dominate the comparison. Pooling all individual gaps from a
      single user still only passed 43/50 random seeds. Fixed by
      pooling gaps across a 15-user population instead of one user,
      using the quick-return ratio the compulsiveness features were
      actually designed to support — stable across 50/50 seeds tested.
- [x] M3: Temporal features (`temporal.py`) — `late_night_usage_pct`
      (23:00-04:00, matching the generator's own late-night window),
      `hourly_usage_entropy` (Shannon entropy over hour-of-day,
      normalized to [0,1]), `weekend_usage_ratio` (duration-weighted).
      Validated end-to-end against the synthetic generator: Doomscroller
      recovers a late_night_usage_pct of ~0.36 against its designed
      `late_night_session_fraction=0.35`; Binge Weekend shows a
      weekend_usage_ratio of ~0.78 vs. Balanced's ~0.29.
- [x] M3: Transition feature (`transitions.py`) —
      `productive_interruption_rate`: fraction of sessions whose
      immediately-preceding app (via `transition_from`) was
      PRODUCTIVE-category, reading `SessionBuilder`'s pre-computed
      per-user chronological transitions rather than recomputing them.
- [x] M3: `feature_vector.py` — assembles every M1-M3 feature into one
      `FeatureVector` per (user, app, day) group. This closes out M3
      entirely, and is the type M4 (heuristic scorer), M5 (LightGBM
      training data), and `mock_backend`'s API response all build on
      from here on, rather than each caller re-assembling individual
      feature calls separately.
- [x] Unit tests: 158 passing total
- [x] `mock_backend/` — a FastAPI service (separate from the real M8
      backend, which doesn't exist yet) that runs the real pipeline
      end-to-end: synthetic generation → dedup → session building →
      outlier capping → windowing → full `FeatureVector` computation,
      exposed via `POST /simulate-day`. Nothing in its response is
      fabricated — it's the real M1-M3 pipeline with no persistence
      layer yet. Addiction/distraction scoring fields will be added
      here as M4-M7 are built.
- [x] `attention-collector-android/` — a Kotlin + Jetpack Compose
      Android app (archetype picker → "Simulate a day" → dashboard)
      that calls `mock_backend`'s `/simulate-day` and displays the
      real per-app `FeatureVector` output. Does **not** yet read real
      device usage data (that's M9's scope) — it's a client
      demonstrating the pipeline, with a visibly separate "Scoring &
      Explainability — in progress" panel for M4-M7's not-yet-built
      output.
  - **Standing rule going forward:** every milestone from M4 onward
    ships with a corresponding update to `mock_backend`'s response
    schema and the Android dashboard, so the app always reflects the
    project's actual current capability rather than going stale.
- [ ] M4: Heuristic Baseline scorer (next)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -e .
```

## Running tests

```bash
pytest
```

## Project layout

```
src/attention_tracker/          # all package code, organized by module (M1-M10)
tests/                           # mirrors src/ — one test module per source module
config/                          # YAML configs, populated during Phase 3 (Ch. 9.2)
mock_backend/                    # FastAPI demo service running the real pipeline
                                  # end-to-end (not the real M8 backend — no
                                  # persistence, no auth; a stand-in until M8 exists)
attention-collector-android/     # Kotlin + Jetpack Compose Android client
                                  # (calls mock_backend today; will point at the
                                  # real M8 service once it exists)
demo_pipeline.py                 # CLI script exercising the full current pipeline
                                  # end-to-end for manual inspection
dashboard/                       # React dashboard (Phase 4, M10 — not yet built)
```

## Try it yourself

```python
from datetime import datetime, timezone
from attention_tracker.synthetic.archetypes import DOOMSCROLLER
from attention_tracker.synthetic.generator import SyntheticEventGenerator
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

gen = SyntheticEventGenerator()
events = gen.generate(
    user_id="demo_user",
    profile=DOOMSCROLLER,
    start_date=datetime(2026, 8, 3, tzinfo=timezone.utc),
    num_days=7,
)

# Full pipeline: dedup -> session building -> outlier capping
result = run_data_quality_pipeline(events)

# Group into (user, app, day) windows and compute every M1-M3 feature
taxonomy = TaxonomyLoader()
windows = group_sessions_by_user_app_day(result.sessions)
for (user_id, package_name, day), sessions in windows.items():
    fv = build_feature_vector(sessions, taxonomy)
    print(f"{package_name} on {day}: {fv.session_count} sessions, "
          f"{fv.late_night_usage_pct:.0%} late-night")
```

Or run `python demo_pipeline.py` for a full pipeline walkthrough with
printed output at every stage.

## Running the mock backend + Android app

`mock_backend/` and `attention-collector-android/` together let you
see the pipeline's output on an actual (emulated) phone screen, ahead
of the real M8/M9 milestones existing:

```bash
pip install fastapi uvicorn
uvicorn mock_backend.main:app --port 8000
```

Then open `attention-collector-android/android-app/` in Android
Studio, run it on an emulator (pre-configured to reach
`10.0.2.2:8000`, the emulator's alias for the host machine's
localhost), pick an archetype, and tap "Simulate a day." The dashboard
shows the real computed `FeatureVector` for that simulated day —
nothing displayed is fabricated, though the data source itself is
synthetic (M9's real on-device collector doesn't exist yet).

**Standing rule:** every milestone from M4 onward should add a
corresponding field to `mock_backend`'s `/simulate-day` response and
a corresponding section in the Android dashboard, so this app stays
an accurate live reflection of the project's current capability
rather than freezing at today's snapshot.