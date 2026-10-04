# Changelog

Newest first. Older milestones (M1–M5) are in the log at the bottom.

## Phase 0 — hardening (Oct 2026)

- Fixed: the synthetic distillation dataset differed between runs
  (`hash(archetype.name)` is randomized per process). Now `zlib.crc32`;
  covered by a cross-process regression test with different
  `PYTHONHASHSEED` values.
- Fixed: `pip install -e .` failed on a clean environment because
  `pyyaml` was missing from `pyproject.toml`.
- Changed: `train_model()` now uses a group-aware train / validation /
  test split. Early stopping watches validation only; the test split is
  report-only. `TrainResult` gained `val_distillation` and
  `best_iteration`. With a minimum-improvement threshold, early stopping
  fires at ~230 rounds (it previously ran into the 200-round cap).
  Test R² against the heuristic: addiction 0.989, distraction 0.981
  (still a distillation score, not accuracy).
- Added: a minimal ruff config in `pyproject.toml` (syntax errors and
  unused code only); removed 7 unused imports it found.
- Moved: the long running status log from README to this file.
- Tests: 322 passing.

---

## Milestone log (M1–M5)

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
- [x] Unit tests: 283 passing total
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
      it's the real M1-M4 pipeline with no persistence layer yet. M5's
      LightGBM models exist in `models/` but aren't wired into this
      response yet; LSTM/autoencoder/SHAP fields follow as M6-M7 are
      built.
- [x] `attention-collector-android/` — a Kotlin + Jetpack Compose
      Android app (archetype picker → "Simulate a day" → dashboard)
      that calls `mock_backend`'s `/simulate-day` and displays the
      real per-app `FeatureVector` output, the M4 heuristic score
      (a colored 0-10 badge on each app card), and the day's
      completeness assessment. Does **not** yet read real device usage
      data (that's M9's scope) — it's a client demonstrating the
      pipeline, with a visibly separate "Model-based scoring — still
      in progress" panel for M5's LightGBM output (built, not yet
      wired into this app) and M6-M7's not-yet-built output.
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
- [x] M5: `models/` — LightGBM distillation of the M4 heuristic into
      "addiction" and "distraction" regressors:
  - `dataset.py` — `feature_row()` encodes a `FeatureVector` + its
    app's `AppCategory` into an 18-column numeric row (12 engineered
    features + 6 one-hot category columns); a one-session window's
    undefined features (`interarrival_mean_sec`,
    `interarrival_under_2min_ratio`) are encoded as NaN, never 0, so
    the model can split on "undefined" instead of "zero." `Dataset`
    holds `rows`/`targets`/`groups` (one synthetic user id per row).
  - `synthetic_dataset.py` — `build_synthetic_distillation_dataset()`
    runs the real generator → data-quality pipeline → weekly windowing
    → feature extraction → heuristic scoring for every (archetype,
    seed) pair, treating each as one synthetic "user" so a group-aware
    split can hold out entire people, not just rows.
  - `lightgbm_scorer.py` — `group_train_test_split()` splits by unique
    user id rather than by row, since two weekly windows of the same
    synthetic user are highly correlated and a row-level split would
    mostly test memorization. `train_model()` trains either model
    `kind` ("addiction": all 18 columns; "distraction": excludes the
    two compulsive-re-opening-frequency columns) and returns a
    `DistillationReport` per side. `retarget_dataset()` swaps the
    training target to a per-user label dict (e.g. a real SAS-SV
    mean) for the day a pilot exists, dropping unlabeled users rather
    than guessing.
  - `model_evaluation.py` — three checks that stay meaningful even
    though the training target is circular: `archetype_ranking_check()`
    generates FRESH synthetic users on a held-out seed range and
    checks whether the model's mean predicted score per archetype
    preserves `COMPULSIVE_CHECKER > DOOMSCROLLER > DEEP_WORKER`, the
    ordering the archetypes were designed to exhibit;
    `correlation_against_heuristic()` computes the Spearman rank
    correlation between model and heuristic on the same windows;
    `stability_under_perturbation()` retrains on Gaussian-noised
    copies of the inputs (noise scaled by each column's own stdev,
    NaNs left untouched) and re-checks the ordering, to see whether it
    is a robust archetype-separation property or a fragile accident of
    one random seed. On the default synthetic configuration: the test
    split reaches R² ≈ 0.98-0.99 against the heuristic (expected — see
    the model's own caveat below), Spearman rho ≈ 0.995 between model
    and heuristic, archetype ordering holds on fresh held-out users,
    and that ordering survived every noise level tried (0.05x-100x
    each column's stdev) — evidence the five archetypes are
    statistically well-separated on these features, not evidence that
    an arbitrary LightGBM model is robust in general.
  - Every `DistillationReport` carries a non-waivable caveat: it
    measures how well the model reproduces the M4 heuristic on
    held-out synthetic users, which is expected since the heuristic is
    a deterministic function of the model's own inputs — not accuracy
    against real problematic use, which no label for yet exists.
  - Not yet wired into `mock_backend`'s API response or the Android
    dashboard — that's a standing follow-up, not part of M5 itself.
- [x] Unit tests: 318 passing total (283 M1-M4/Phase 1-2, 35 M5)