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

## Status: Phase 1 — Data Foundation (M4 complete)

- [x] M1: Schema Layer — `RawEvent`, `Session`, `AppMetadataEntry`,
      `TaxonomyLoader` + 50-app seed taxonomy
- [x] M2: Synthetic Data Generator — all 5 archetypes (`BALANCED`,
      `DOOMSCROLLER`, `BINGE_WEEKEND`, `DEEP_WORKER`,
      `COMPULSIVE_CHECKER`) + population generation
- [x] M3: `SessionBuilder` — joins OPENED/CLOSED event pairs into
      `Session` records via FIFO pairing per (user, package), with
      `transition_from` / `transition_to` from each user's
      chronological session order. Each `Session` carries the closing
      event's `tz_offset_minutes` and exposes `local_start_time`. A
      pair that fails `Session` validation is recorded in
      `rejected_pairs` rather than aborting the batch, and the
      builder falls through to the next-oldest pending open
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
- [x] Data-quality stage — added after
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
    a stale wake-lock producing a 14-hour "session"). Also reports
    any same-user sessions that still overlap after capping
    (`overlapping_session_ids`)
  - `pipeline/quality/pipeline.py` — orchestrates dedup → session
    building → outlier capping as one callable stage, so the fix
    actually runs in the pipeline rather than existing only as
    independently-tested modules
  - `pipeline/quality/completeness.py` — `assess_day_completeness()`,
    a documented PLACEHOLDER heuristic: flags a user's day if the
    largest session-free gap (across all their apps) exceeds 6 hours.
    Cannot distinguish a real sync failure from genuine non-use — that
    needs M9's real Android sync-heartbeat signal, which doesn't exist
    yet. Explicitly designed to be replaced (not just kept around) once
    M9 lands.
- [x] M3: `windowing.py` — groups sessions by (user, app, local
      calendar day), pre-sorted by local start time, as the shared
      grouping every feature function builds on
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
- [x] M3: Temporal features (`temporal.py`) — computed from the
      user's local time, not UTC. `late_night_usage_pct`
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
- [x] Unit tests: 318 passing total
- [x] **External review response** — an outside review of the
      project's scientific validity identified 37 numbered
      weaknesses. Addressed the fixable ones directly:
  - Measured (not assumed) correlation between
    `sessions_under_30s_ratio`, `interarrival_under_2min_ratio`, and
    `session_count` — found the first two are essentially
    uncorrelated (-0.06), and `session_count`'s correlation with
    `sessions_under_30s_ratio` (0.39) is moderate, not severe. No
    weight change was warranted; documented the measurement in
    `scoring/config.py` rather than "fixing" a redundancy that didn't
    hold up.
  - Added `late_night_usage_time_ratio` (duration-weighted), since
    the original `late_night_usage_pct` counted sessions — a 5-second
    late-night check and a 90-minute binge scored identically. Both
    are kept; the heuristic scorer now uses the duration-weighted one.
  - Reframed `hourly_usage_entropy`'s role: low entropy (concentrated
    usage) isn't inherently risky — a student in back-to-back classes
    also has low entropy — so it's now dampened for PRODUCTIVE apps,
    the same fix already applied to the volume term.
  - Documented, rather than silently left implicit: the app
    taxonomy's single-category-per-app simplification (a YouTube
    example is written out explicitly), the 0.3 productive-app
    dampener's chosen-not-derived status, an intended
    permission-denial handling design for M9, and a privacy-position
    statement for M8/M9.
  - Added a weight-sensitivity test suite: perturbed each of the 8
    heuristic weights by ±25% individually and re-checked the core
    archetype ordering. **Result: the ordering held in all 16
    perturbations tested** — a genuine, positive finding that the
    scorer isn't a knife-edge result of the exact chosen weights.
  - **Explicitly documented as NOT fixable by code** (see
    `docs/architecture.md`, "Known limitations"): the absence of
    real-world ground-truth labels, the circular validation inherent
    to testing a heuristic against the same synthetic archetypes it
    was designed around, and the fact that M5's LightGBM will learn
    to approximate this heuristic rather than independent truth.
    These require real user data to resolve, not more engineering.
- [x] `mock_backend/` — a FastAPI service (separate from the real M8
      backend, which doesn't exist yet) that runs the real pipeline
      end-to-end: synthetic generation → dedup → session building →
      outlier capping → completeness assessment → windowing → full
      `FeatureVector` computation → M4 heuristic scoring, exposed via
      `POST /simulate-day`, including `rejected_pairs_count` and
      `overlapping_sessions_count` diagnostics. Covered by
      `tests/mock_backend/`. Nothing in its response is fabricated —
      it's the real M1-M4 pipeline with no persistence layer yet.
      LightGBM/LSTM/autoencoder/SHAP fields will be added here as
      M5-M7 are built.
- [x] `attention-collector-android/` — a Kotlin + Jetpack Compose
      Android app (archetype picker → "Simulate a day" → dashboard)
      that calls `mock_backend`'s `/simulate-day` and displays the
      real per-app `FeatureVector` output, the M4 heuristic score
      (a colored 0-10 badge on each app card), and the day's
      completeness assessment. Does **not** yet read real device usage
      data (that's M9's scope) — it's a client demonstrating the
      pipeline, with a visibly separate "Model-based scoring — still
      in progress" panel for M5-M7's not-yet-built output.
  - **Standing rule going forward:** every milestone from M4 onward
    ships with a corresponding update to `mock_backend`'s response
    schema and the Android dashboard, so the app always reflects the
    project's actual current capability rather than going stale. M4
    itself is the first milestone this rule applied to — its
    heuristic score is real and visible in the app, not left as a
    placeholder.
- [x] M4: Heuristic Baseline scorer (`scoring/heuristic.py`,
      `scoring/config.py`) — normalizes each `FeatureVector` field to
      [0,1] and combines via explicit, individually-justified weights
      into a 0-10 score. Weights and normalization bounds are
      documented in `scoring/config.py` rather than left as an
      illustrative split.
  - **Design finding caught by test-first validation:** an early
    version scored `DEEP_WORKER` (long, focused sessions on a single
    PRODUCTIVE app) *higher* on average than `DOOMSCROLLER` and
    `BINGE_WEEKEND` — `total_time_sec` and inverted
    `hourly_usage_entropy` don't know which app they're measuring, so
    a long focused productive session looked mathematically identical
    to a long compulsive one. Fixed by requiring the app's
    `AppCategory` as an explicit scorer input and applying a
    `productive_app_dampener` (0.3×) to the volume/entropy
    contributions when the app is PRODUCTIVE-category. Caught and
    fixed before the weights were trusted, exactly per the project's
    test-first approach for this scorer.
  - Validated via archetype-ordering (the only validation available —
    no ground-truth addiction label exists for any user): across all
    five archetypes and 30 seeds each, `COMPULSIVE_CHECKER` >
    `DOOMSCROLLER` > `DEEP_WORKER`/`BALANCED`, and `DOOMSCROLLER` >
    `DEEP_WORKER` specifically (the exact comparison that failed
    pre-fix), each holding at a required 27/30-seed pass rate.
  - This score is the training TARGET for M5's LightGBM models, since
    no true ground-truth label exists — M5 learns a smoother
    approximation of this heuristic, not "true addiction."

- [x] Scoring uses the app's category, not just PRODUCTIVE-vs-rest:
      `NormalizationBounds.category_multipliers` scales the final score
      (ADDICTIVE 1.0, ENTERTAINMENT 0.85, COMMUNICATION and UNKNOWN 0.7,
      UTILITY 0.5, PRODUCTIVE 0.3), so the same behavior scores higher
      on a feed than on a document editor. Multipliers are chosen, not
      derived. Features undefined for a one-session window
      (`interarrival_under_2min_ratio`, `hourly_usage_entropy`) are
      left out and the remaining weights renormalized.
- [x] `group_sessions_by_user_app_week()` — (user, app, ISO-week)
      windows. Over a week `weekend_usage_ratio` is a real share of
      time (a one-day window can only give 0 or 1), and single-session
      windows roughly halve.
- [x] Weight-sensitivity suite extended: every weight perturbed by
      ±25% and ±50% (ordering held in all cases), the full
      five-archetype ordering, and random weight vectors. With fully
      random weights the ordering broke in 5 of 15 draws, always when
      one signal dominated (late-night dominant lets `DOOMSCROLLER`
      overtake `COMPULSIVE_CHECKER`; productive-interruption dominant
      lets `DEEP_WORKER` overtake `DOOMSCROLLER`). The ordering is
      robust to proportional re-weighting, not to letting one feature
      dominate; both cases are pinned by tests.
- [x] `config/app_taxonomy_extended.yaml` — ~115 real-device apps
      (Indian and global) plus an `ignored_packages` list of system
      surfaces (launchers, system UI, keyboards, dialers, installers).
      Opt in with `TaxonomyLoader(include_extended=True)`; the default
      loader stays seed-only because the synthetic generator draws
      from it. Coverage of a 20-app realistic Indian Android sample:
      95%+ (seed alone: 28%). `run_data_quality_pipeline(taxonomy=...)`
      drops system-app events before session building so they do not
      appear in the transition chain.
- [x] `pipeline/sequences.py` — one ordered sequence per user per local
      day across all apps (log duration, log gap, cyclic hour, weekend,
      app-switch, category one-hot; padded with a mask), the input M6's
      LSTM needs.
- [x] `evaluation/` — SAS-SV self-report label ingestion
      (`labels.py`) and validation metrics (`validation.py`): rank
      correlation between a per-user score and a per-user SAS-SV total
      with a bootstrap interval, and a distillation report that always
      states it is not accuracy. A plain linear fit on the heuristic's
      own inputs reaches R² ≈ 0.94 on held-out synthetic users, so
      agreement with the heuristic is expected and proves nothing about
      real problematic use. How to collect the labels:
      [`docs/validation_protocol.md`](docs/validation_protocol.md).

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
                                  # incl. evaluation/ (labels + validation metrics)
tests/                           # mirrors src/ — one test module per source module
config/                          # app taxonomies (seed + extended); more YAML in Phase 3
docs/                            # architecture.md, validation_protocol.md
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
of the real M8/M9 milestones existing. `fastapi`, `uvicorn` and
`httpx` come from `requirements.txt` (see [Setup](#setup)):

```bash
uvicorn mock_backend.main:app --port 8000
```

Then open `attention-collector-android/android-app/` in Android
Studio, run it on an emulator (pre-configured to reach
`10.0.2.2:8000`, the emulator's alias for the host machine's
localhost), pick an archetype, and tap "Simulate a day." The dashboard
shows the real computed `FeatureVector` for that simulated day, each
app's M4 heuristic score, and a completeness indicator for the day —
nothing displayed is fabricated, though the data source itself is
synthetic (M9's real on-device collector doesn't exist yet).

**Standing rule:** every milestone from M4 onward should add a
corresponding field to `mock_backend`'s `/simulate-day` response and
a corresponding section in the Android dashboard, so this app stays
an accurate live reflection of the project's current capability
rather than freezing at today's snapshot.