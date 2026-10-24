# Architecture

This document maps the modules that actually exist in this repository
today, and how data actually flows between them. It is regenerated
(not just appended to) whenever a milestone changes the shape of the
pipeline — the goal is that this file is never more than one
milestone stale, unlike the README status list, which is a running
log of everything ever done.

Every arrow below was confirmed by reading the actual `import`
statements in the source files, not written from memory of the
original design.

## Data flow, end to end (current state: M1–M5 complete)

```
                     ┌─────────────────────────┐
                     │  SyntheticEventGenerator │   (synthetic/generator.py)
                     │  + ArchetypeProfile      │   (synthetic/archetypes.py)
                     └────────────┬─────────────┘
                                  │  list[RawEvent]
                                  ▼
                     ┌─────────────────────────┐
                     │  run_data_quality_       │   (pipeline/quality/pipeline.py)
                     │  pipeline()              │
                     │                          │
                     │  1. dedupe_events()      │   (pipeline/quality/dedup.py)
                     │  2. SessionBuilder.build()│  (pipeline/session_builder.py)
                     │  3. cap_session_outliers()│  (pipeline/quality/outliers.py)
                     └────────────┬─────────────┘
                                  │  list[Session]
                                  ├─────────────────────────────┐
                                  ▼                             ▼
                     ┌─────────────────────────┐   ┌─────────────────────────┐
                     │  group_sessions_by_      │   │  assess_day_            │
                     │  user_app_day()          │   │  completeness()         │
                     │  (pipeline/windowing.py) │   │  (pipeline/quality/     │
                     └────────────┬─────────────┘   │   completeness.py)      │
                                  │                  │  — placeholder heuristic│
                                  │                  │    until M9's real sync │
                                  │                  │    heartbeat exists     │
                                  │                  └────────────┬────────────┘
                                  │  dict[(user, app, day), list[Session]]     │
                                  ▼                                           │
                     ┌─────────────────────────┐                             │
                     │  build_feature_vector()  │   (pipeline/features/       │
                     │  — calls, per group:     │    feature_vector.py)       │
                     │    volume.py             │                             │
                     │    compulsiveness.py     │                             │
                     │    temporal.py           │                             │
                     │    transitions.py        │                             │
                     └────────────┬─────────────┘                             │
                                  │  FeatureVector (one per user/app/day)      │
                                  ▼                                           │
                     ┌─────────────────────────┐                             │
                     │  compute_heuristic_      │   (scoring/heuristic.py,   │
                     │  score()                 │    scoring/config.py)       │
                     │  — needs FeatureVector + │                             │
                     │    the app's AppCategory │                             │
                     └────────────┬─────────────┘                             │
                                  │  float, 0-10                               │
                                  ▼                                           ▼
                     ┌─────────────────────────────────────────────────────────┐
                     │  mock_backend/main.py    │   FastAPI: POST /simulate-day │
                     │  (demo layer, not M8)    │                              │
                     └────────────┬────────────────────────────────────────────┘
                                  │  JSON over HTTP
                                  ▼
                     ┌─────────────────────────┐
                     │  Android app             │   Kotlin + Compose
                     │  (attention-collector-   │   (calls mock_backend today;
                     │   android/)              │    will point at real M8 later)
                     └─────────────────────────┘
```

Everything above the `mock_backend` box is real project logic, fully
tested (346 tests, including M5's `models/`). `mock_backend` and the
Android app are demo/integration layers — they call the real pipeline
but are not themselves M8 or M9's actual scope (see "Demo layer and
production scope" below).

## Module reference

### `schema/` — the shared vocabulary every other module imports

No internal dependencies — this is the base layer everything else
builds on.

- **`raw_event.py`** — `RawEvent`, `EventType`, `TERMINAL_EVENT_TYPES`.
  The validated shape of one OPENED/CLOSED/BACKGROUND/FOREGROUND event.
  Rejects naive timestamps, negative durations, and mismatched
  terminal/opening fields at construction time.
- **`session.py`** — `Session`. The joined shape of one matched
  OPENED+CLOSED pair, with `transition_from`/`transition_to` for the
  apps immediately before/after. Validates internal consistency
  (`end_time - start_time == duration_sec`, within float slack).
  Carries `tz_offset_minutes` (from the closing event) and exposes
  `local_start_time`, the UTC `start_time` shifted by that offset.
  Temporal features and windowing read `local_start_time`;
  `start_time` itself is always UTC.
- **`app_metadata.py`** — `AppCategory` enum (PRODUCTIVE, ADDICTIVE,
  ENTERTAINMENT, COMMUNICATION, UTILITY, UNKNOWN).
- **`app_metadata_entry.py`** — `AppMetadataEntry`, the validated shape
  of one taxonomy row (imports `app_metadata.py`).
- **`taxonomy_loader.py`** — `TaxonomyLoader`, reads
  `config/app_taxonomy.yaml` and exposes `.lookup(package_name)`,
  falling back to `AppCategory.UNKNOWN` for unrecognized packages
  rather than raising (imports `app_metadata.py`,
  `app_metadata_entry.py`). `TaxonomyLoader(include_extended=True)`
  also merges `config/app_taxonomy_extended.yaml`: ~115 further
  real-device apps (Indian and global), with the seed winning on any
  overlap, plus an `ignored_packages` list of system surfaces
  (launchers, system UI, keyboards, dialers, installers) exposed via
  `is_ignored()`. The default loader stays seed-only because the
  synthetic generator draws apps by category from it. The extended
  layer is for lookups against real device data.

### `synthetic/` — fabricates realistic event streams for testing

Depends on `schema/` only.

- **`archetypes.py`** — `ArchetypeProfile` dataclass + five registered
  profiles (`BALANCED`, `DOOMSCROLLER`, `BINGE_WEEKEND`,
  `DEEP_WORKER`, `COMPULSIVE_CHECKER`) in the `ARCHETYPES` dict.
  Imports `schema/app_metadata.py` for category weighting.
- **`generator.py`** — `SyntheticEventGenerator`. `.generate_day()` /
  `.generate()` / `.generate_population()` produce `RawEvent` streams
  from an `ArchetypeProfile`. Imports `schema/raw_event.py`,
  `schema/app_metadata.py`, `schema/taxonomy_loader.py`, and
  `synthetic/archetypes.py`. Late-night starts draw hours
  23, 0, 1, 2, 3 evenly; hour 23 falls on the base day and hours 0-3
  on the following day.

### `pipeline/quality/` — cleans the raw event/session stream

- **`dedup.py`** — `dedupe_events()`. Removes duplicate `RawEvent`s:
  `session_id` as idempotency key for terminal events, exact
  `(user_id, package_name, timestamp)` match for opening events that
  have none yet. Depends on `schema/raw_event.py` only. The match is
  exact (no tolerance window), since no real-device retry timing
  exists yet to calibrate one against; revisit under M9.
- **`outliers.py`** — `cap_session_outliers()`. Caps session durations
  at a device-plausibility bound (`MAX_PLAUSIBLE_SESSION_SEC`, 4
  hours) rather than a statistical percentile, so genuine heavy-usage
  days aren't clipped alongside measurement errors. Depends on
  `schema/session.py` only. Also returns `overlapping_session_ids`:
  same-user session pairs whose intervals still overlap after
  capping. Reported, not corrected — duration alone can't say which
  of two overlapping sessions is real. The sweep tracks the latest
  end time seen so far per user, so a long session containing two
  shorter non-overlapping ones flags both.
- **`pipeline.py`** — `run_data_quality_pipeline()`. The orchestration
  point: dedup → `SessionBuilder.build()` → outlier capping, in that
  fixed order, as one callable. When given a taxonomy it drops
  system-app events between dedup and session building. That
  ordering matters: a launcher session left in place would sit
  between two real apps in `transition_from`/`transition_to`. This is the only place that ordering
  logic lives; every other caller (the demo script, `mock_backend`)
  calls this function rather than re-chaining the three stages.
  Depends on `dedup.py`, `outliers.py`, `pipeline/session_builder.py`,
  `schema/raw_event.py`, `schema/session.py`.
- **`completeness.py`** — `assess_day_completeness()`. A **documented
  placeholder heuristic**: flags a user's day as suspicious if the
  largest session-free gap (across ALL the user's apps, not one)
  exceeds a threshold (default 6 hours). Cannot distinguish a real
  sync failure from genuine non-use — that distinction needs M9's
  Android sync heartbeat, which M9 adds. Takes the full
  `list[Session]` for one user-day (not a
  `group_sessions_by_user_app_day()` output, which is scoped to one
  app). Depends on `schema/session.py` only. `result.day` is the
  user's local calendar day.

### `pipeline/` (top level) — turns events into sessions, sessions into windows

- **`session_builder.py`** — `SessionBuilder`. FIFO-pairs OPENED with
  CLOSED/BACKGROUND events per `(user_id, package_name)`, and computes
  `transition_from`/`transition_to` per user across ALL apps
  chronologically (not per-window — this is why
  `productive_interruption_rate` can read a pre-computed value rather
  than needing cross-window context itself). Depends on
  `schema/raw_event.py`, `schema/session.py`. A matched pair that
  fails `Session` validation goes to `SessionBuildResult.rejected_pairs`
  instead of aborting the batch, and the builder tries the next-oldest
  pending open for that key. A rejected open is dropped, not
  re-queued, and is not also listed in `unmatched_opens`.
- **`windowing.py`** — `group_sessions_by_user_app_day()`. Groups a
  flat `list[Session]` into `dict[(user, package, day), list[Session]]`,
  pre-sorted by `local_start_time` within each group. Depends on
  `schema/session.py` only. A session's full duration is attributed
  to its local start day, even if it runs past local midnight.
  `group_sessions_by_user_app_week()` groups on the Monday of the
  session's local ISO week instead. A one-day window can only see one
  weekday, so `weekend_usage_ratio` there is 0 or 1; over a week it is
  a real share of time, and interarrival and entropy get more than one
  session to work with (roughly half as many single-session windows on
  the synthetic archetypes).
- **`sequences.py`** — `build_day_sequences()`. One ordered sequence
  per user per local day across ALL apps, the input shape M6's LSTM
  needs (the M3 windows are per-app bags with no cross-app order).
  Each step is a fixed numeric vector: `log1p` duration, `log1p` gap
  since the previous session (clipped at 6 h), cyclic hour-of-day
  (sin/cos), weekend flag, app-switch flag, and a category one-hot.
  Sequences are padded to `max_len` with a mask; truncation keeps the
  last steps and reports how many were dropped. Plain lists, no
  torch/numpy. Depends on `schema/session.py`,
  `schema/taxonomy_loader.py`.

### `pipeline/features/` — computes behavioral features per window

Every function here takes a pre-grouped, pre-sorted
`list[Session]` (one `(user, app, day)` group) and returns a scalar or
`FeatureVector`. None of these functions call `windowing.py`
themselves — grouping is the caller's job.

- **`volume.py`** — `total_time_sec`, `session_count`,
  `avg_session_duration_sec`, `max_session_duration_sec`. Depends on
  `schema/session.py` only.
- **`compulsiveness.py`** — `interarrival_mean_sec`,
  `sessions_under_30s_ratio`, `interarrival_under_2min_ratio`. Depends
  on `schema/session.py` only. Requires ≥2 sessions for the
  interarrival functions (raises `ValueError` below that).
- **`temporal.py`** — `late_night_usage_pct` (session-COUNT-based,
  23:00–04:00, matching the generator's own late-night window
  definition exactly), `late_night_usage_time_ratio` (the
  duration-weighted counterpart: a 5-second late-night check and a
  90-minute late-night session count differently — both are kept
  since they answer different questions), `hourly_usage_entropy`
  (Shannon entropy over hour-of-day, normalized to [0,1]),
  `weekend_usage_ratio` (duration-weighted, not count-weighted).
  Depends on `schema/session.py` only.
- **`transitions.py`** — `productive_interruption_rate`. Reads each
  session's `transition_from` (populated by `SessionBuilder`, not
  recomputed here) and resolves it to a category via `TaxonomyLoader`.
  Depends on `schema/session.py`, `schema/taxonomy_loader.py`,
  `schema/app_metadata.py`.
- **`feature_vector.py`** — `FeatureVector` (frozen dataclass) +
  `build_feature_vector()`. Assembles every feature above into one
  object per `(user, app, day)` group. This is the type M4's heuristic
  scorer, M5's LightGBM training data, and `mock_backend`'s API
  response should all consume — not individual feature calls
  re-assembled per caller. Depends on all four feature modules above,
  plus `schema/session.py`, `schema/taxonomy_loader.py`.

### `scoring/` — M4 heuristic baseline and distraction heuristic (M5's training targets)

- **`config.py`** — `HeuristicWeights` (validates weights sum to 1.0)
  and `NormalizationBounds`. Every weight and bound is documented with
  its justification in the module docstring, including a
  **design-finding writeup**: an early version scored `DEEP_WORKER`
  higher than `DOOMSCROLLER` on average because `total_time_sec` and
  entropy didn't distinguish which app was being used. No internal
  dependencies.
- **`heuristic.py`** — `compute_heuristic_score()`. Normalizes each
  `FeatureVector` field to [0, 1] and combines via `config.py`'s
  weights into a 0-10 score. Requires the app's `AppCategory` as an
  explicit input (not looked up internally). The category acts in two
  places: `productive_app_dampener` scales the volume and entropy
  terms for PRODUCTIVE apps, and `NormalizationBounds.category_multipliers`
  scales the final score by how attention-capturing the category is
  (ADDICTIVE 1.0, ENTERTAINMENT 0.85, COMMUNICATION and UNKNOWN 0.7,
  UTILITY 0.5, PRODUCTIVE 0.3), so identical behavior scores higher
  on a feed than on a document editor. The multipliers are chosen,
  not derived. Features that are undefined for a one-session window
  (`interarrival_under_2min_ratio` is `None`; `hourly_usage_entropy`
  is meaningless) are left out and the remaining weights renormalized,
  rather than scored as 0 or as "perfectly concentrated". This score is the M5 LightGBM training TARGET, since no true
  ground-truth addiction label exists. Depends on
  `pipeline/features/feature_vector.py`, `schema/app_metadata.py`,
  `scoring/config.py`.
- **`distraction.py`** — `compute_distraction_score()`, the distraction
  heuristic (0-10) and the M5 distraction model's training target. It
  measures how fragmented attention is, not how compulsive: weights are
  short sessions .25, productive-app interruptions .25, rapid
  re-opening .20, session count .15, hourly entropy .10 (high entropy,
  usage scattered across the day, scores higher; the addiction
  heuristic reads it the other way) and total time .05. Late-night and
  weekend usage carry no weight. Category multipliers differ too
  (ADDICTIVE and COMMUNICATION 1.0, ENTERTAINMENT 0.85, UNKNOWN 0.7,
  UTILITY 0.4, PRODUCTIVE 0.2). On the default synthetic dataset its
  Spearman rank correlation with the addiction heuristic is about 0.70,
  so the two models learn different targets. Like the addiction
  heuristic it is expert-weighted and unvalidated against real users.
  `DistractionWeights` in `config.py` validates the weights sum to 1.0.
  **Validation:** archetype-ordering only (no ground truth exists) —
  see `tests/scoring/test_heuristic.py`, run across all five
  archetypes and 30 seeds each at a 27/30 pass-rate bar, matching the
  rigor used for the M3 interarrival-statistic fix.

### `evaluation/` — what a score is allowed to claim

Depends on nothing else in the package; pure Python.

- **`labels.py`** — `SasSvResponse`: one participant's SAS-SV answers
  (10 items, 1-6, total 10-60) linked by pseudonymous `user_id`, with
  the published sex-specific cut-offs (31 male, 33 female, at or
  above). Sex unspecified gives no binary flag, because a cut-off
  would have to be guessed. Item wording is not reproduced. Cut-offs
  come from Korean adolescents, so the continuous total is the
  primary quantity. Holds no data.
- **`validation.py`** — two deliberately separate checks.
  `score_vs_label_validity()` is construct validity: Spearman rank
  correlation between a per-user score and a per-user SAS-SV total,
  with a bootstrap interval over resampled users, refusing to
  interpret fewer than 20 users and stating in words whether the
  interval shows tracking, no relationship, or an inverse one.
  `distillation_report()` measures how well a model reproduces the
  heuristic and always carries a caveat saying it is not accuracy:
  the heuristic is a deterministic function of the model's own
  inputs, and a plain linear fit on those inputs already reaches
  R² ≈ 0.94 on held-out synthetic users.
- Protocol for collecting the labels: `docs/validation_protocol.md`.

### `models/` — M5 LightGBM distillation (M6's LSTM/autoencoder still reserved)

Depends on `pipeline/features/feature_vector.py`, `schema/app_metadata.py`,
`scoring/heuristic.py`, `scoring/distraction.py`, `synthetic/`,
`evaluation/validation.py`.

- **`dataset.py`** — `COLUMN_NAMES` (18 columns: 12 engineered
  features + 6 one-hot `AppCategory` columns). `feature_row(fv,
  category)` encodes one `FeatureVector` + category into a row
  matching `COLUMN_NAMES`; a feature that's undefined for a
  one-session window (`interarrival_mean_sec`,
  `interarrival_under_2min_ratio`) becomes `float('nan')`, never `0`,
  so a tree model can split on "was this defined" rather than being
  told an undefined value behaves like zero. `Dataset` holds
  `rows`/`targets`/`groups` (one synthetic user id per row) plus an
  optional `distraction_targets` (the distraction-heuristic label for
  each row; `targets` stays the addiction label), with
  `__post_init__` validation that all three line up and every row
  matches `COLUMN_NAMES`'s width.
- **`synthetic_dataset.py`** — `SyntheticDatasetConfig`
  (seeds-per-archetype, days, start date, taxonomy) and
  `build_synthetic_distillation_dataset()`: generates one synthetic
  "user" per (archetype, seed), runs each through the real
  `run_data_quality_pipeline()` → `group_sessions_by_user_app_week()`
  → `build_feature_vector()` → `compute_heuristic_score()`, and
  returns every resulting window as one `Dataset` row, labeled by the
  heuristic — the only training target available before a real SAS-SV
  pilot exists. A `seed_offset` parameter draws a disjoint seed range
  from the same archetypes, so a held-out check can generate users the
  training set never saw.
- **`lightgbm_scorer.py`** — `group_train_test_split()` splits by
  unique user id, not by row: two weekly windows from the same
  synthetic user are highly correlated, so a row-level split would
  mostly test memorization of users the model already trained on.
  `train_model()` trains one of two `ModelKind`s — `"addiction"`
  (trained on the addiction heuristic) or `"distraction"` (trained on
  the separate distraction heuristic). Both read all 18 columns; they
  differ by target, not by hidden features. Asking for a distraction
  model on a dataset without `distraction_targets` raises. Returns a
  `TrainResult` with a `DistillationReport` (see `evaluation/
  validation.py`) for the train, validation and test splits.
  `group_train_val_test_split()` splits by user into three disjoint
  sets. Early stopping (50 rounds, minimum improvement 1e-3) watches
  the validation split only; the test split is report-only, so the
  stopping point is never chosen on rows later reported as held out.
  `TrainResult.best_iteration` records where training stopped
  (~230 rounds on the default dataset). The per-user RNG in
  `synthetic_dataset.py` seeds from `zlib.crc32`, not `hash()`, so the
  dataset is identical across processes.
  `TrainedModel.predict()` always accepts FULL-WIDTH rows (all 18
  columns) regardless of the model's `kind`, re-indexing down to its
  own training columns internally; it returns `[]` immediately for empty
  input rather than constructing a malformed array. `retarget_dataset()`
  swaps the training target to a per-user label dict (e.g. a real
  SAS-SV mean once a pilot exists), dropping any row whose user has no
  label rather than guessing one.
- **`model_evaluation.py`** — three checks that stay meaningful even
  though the training target is circular (see "Scope and validation roadmap"
  below): `archetype_ranking_check()` generates FRESH synthetic users
  on a held-out seed range, predicts every window, and checks whether
  the model's mean score per archetype preserves
  `EXPECTED_RISK_ORDER` (`COMPULSIVE_CHECKER > DOOMSCROLLER >
  DEEP_WORKER` — the ordering those archetypes were built to exhibit;
  `BALANCED`/`BINGE_WEEKEND` are deliberately excluded since they were
  designed to sit between the extremes, not anchor either end).
  `correlation_against_heuristic()` computes the Spearman rank
  correlation between model predictions and heuristic scores on the
  same rows — a non-parametric view of agreement that doesn't assume
  the linear relationship R² does. `stability_under_perturbation()`
  retrains a caller-supplied model `n_perturbations` times on
  Gaussian-noised copies of the rows (noise scaled by each column's
  own population stdev, computed ignoring NaNs; NaN values are left
  untouched rather than noised) and re-runs the archetype-ranking
  check each time. On the default synthetic configuration: the test
  split reaches R² ≈ 0.98-0.99 against the heuristic (expected, not
  evidence of real-world accuracy — see the caveat below), Spearman
  rho ≈ 0.995 between model and heuristic, archetype ordering holds on
  fresh held-out users, and that ordering survived every noise level
  tried (0.05x-100x each column's own stdev) — evidence the five
  archetypes are statistically well-separated on these features, not
  evidence that an arbitrary LightGBM model is robust in general.
- Every `DistillationReport` produced here carries
  `evaluation.validation.DISTILLATION_CAVEAT`: a high number measures
  how well the model reproduces the M4 heuristic on held-out synthetic
  users (expected, since the heuristic is a deterministic function of
  the model's own inputs), not accuracy against real problematic use,
  for which no label yet exists.
- **`registry.py`** — saves and loads trained models. Layout:
  `<root>/<kind>/<version>/model.txt` (LightGBM text model) plus
  `meta.json` (kind, version, UTC timestamp, feature columns, LightGBM
  version, best iteration, validation and test R², the distillation
  caveat, and `target: heuristic_distillation_synthetic`). Versions are
  UTC timestamps, so the lexicographically largest directory is the
  newest. `load_model()` refuses a model whose columns the code no
  longer has (retrain instead of mispredicting). The root defaults to
  `models_artifacts/` (git-ignored) or the `ATTENTION_MODEL_DIR`
  environment variable.
- **`train_cli.py`** — `python -m attention_tracker.models.train_cli`
  builds the synthetic dataset, trains both models and saves them to
  the registry.
- **Wired into `mock_backend` and the Android dashboard** (see below).
  M6 (LSTM, autoencoder) and M7 (SHAP) remain open.

### `mock_backend/` — demo integration layer (not the real M8 backend)

- **`main.py`** — FastAPI service. `GET /archetypes` lists the real
  registered archetypes; `POST /simulate-day` runs
  `SyntheticEventGenerator` → `run_data_quality_pipeline` →
  `assess_day_completeness` (day-level) + `group_sessions_by_user_app_day`
  → `build_feature_vector` → `compute_heuristic_score` (per app), and
  returns the result as JSON. No persistence — nothing is stored
  between requests. Depends on `synthetic/generator.py`,
  `synthetic/archetypes.py`, `pipeline/quality/pipeline.py`,
  `pipeline/quality/completeness.py`, `pipeline/windowing.py`,
  `pipeline/features/feature_vector.py`, `scoring/heuristic.py`,
  `scoring/distraction.py`, `models/registry.py`, `models/dataset.py`,
  `schema/taxonomy_loader.py`. Each app in the response carries the
  addiction heuristic, the distraction heuristic and, when trained
  models exist in the registry, `addiction_model_score` and
  `distraction_model_score` (otherwise `null`; `scoring_status` is then
  `heuristic_only`). `model_versions` names the model versions used.
  Models are loaded lazily, so one trained while the server runs is
  picked up on the next request. Response includes
  `rejected_pairs_count` and `overlapping_sessions_count`. Requires
  `fastapi`, `uvicorn`, `httpx` (in `requirements.txt`). Covered by
  `tests/mock_backend/`.

### `attention-collector-android/` — demo Android client (not the real M9 collector)

Kotlin + Jetpack Compose app. Archetype picker → "Simulate a day" →
calls `mock_backend`'s `POST /simulate-day` via Retrofit/Moshi →
displays the returned `FeatureVector` fields plus each app's addiction
and distraction heuristic scores (colored 0-10 badges on each app
card), the LightGBM model scores when the backend has trained models
(shown only then, never as placeholders), and the day's completeness
assessment, with a visually separate "Model-based scoring — still in
progress" panel in which the LightGBM row reads LIVE once models are
loaded and the M6–M7 rows stay pending. Does not read real on-device usage data — see
"Demo layer and production scope" below.

### Reserved for upcoming milestones

These packages exist as empty scaffolding (`__init__.py` only) for
future milestones. Listed here so their emptiness reads as
intentional, not abandoned:

- **`models/` (M6 only)** — M5's LightGBM distillation is built; see
  the `models/` module reference above. M6 (LSTM, autoencoder) is
  still reserved inside the same package.
- **`explainability/`** — M7 (SHAP)
- **`storage/`** — M8 (SQLite persistence)
- **`api/`** — M8 (the real FastAPI service, replacing `mock_backend`)
- **`utils/`** — cross-cutting helpers, populated as needed rather
  than on a fixed milestone

## Demo layer and production scope

`mock_backend/` and the Android app run the real pipeline end to end:
every computation between `SyntheticEventGenerator` and the JSON
response is the tested code from `src/`. What each layer covers today,
and which milestone extends it:

- **Data source.** `mock_backend` generates synthetic days from
  archetype statistics, and the Android app's "Simulate a day" button
  displays them. Reading `UsageStatsManager` on a real phone is M9.
- **Persistence.** `mock_backend` answers each request independently.
  Storage and history are M8's `storage/` scope.
- **Scoring.** The M4 heuristic is a tested, weighted combination of
  real features. M5's LightGBM "addiction" and "distraction" models
  are served by `mock_backend` and shown in the Android dashboard once
  trained with `python -m attention_tracker.models.train_cli`. They
  are trained on synthetic users to reproduce the two heuristics.
  LSTM, autoencoder and SHAP (M6-M7) are next, and the Android
  "Model-based scoring" panel keeps those rows marked pending rather
  than showing placeholder numbers.
- **Completeness.** `assess_day_completeness()` flags gaps in a day's
  data. Telling a sync gap from a day the user did not use the phone
  needs M9's Android sync heartbeat, so an "incomplete" flag means
  "worth a closer look".

## Scope and validation roadmap

The current build is the full engineering pipeline on synthetic data.
Its scores have not yet been compared with real users. This section
states what that means and how the pilot closes it.

| Current scope | What it means | How it is addressed |
|---|---|---|
| Synthetic data, no real-user labels | A score of 7 has no established real-world meaning yet | Pilot of 20+ users with 14+ days of data and SAS-SV self-report (`docs/validation_protocol.md`) |
| Heuristic weights are expert-chosen | Provenance is written into `scoring/config.py` ("WEIGHT PROVENANCE") | Weights tuned on a pilot sample separate from the one used to report validity |
| Archetype checks test internal consistency | The archetypes are built to show the behaviors the scorer detects, so these checks confirm the code does what it was designed to do | Spearman rho with bootstrap CI against SAS-SV on real users |
| M5 models reproduce the heuristic | The R² of about 0.98-0.99 and rho of about 0.995 measure fit to the heuristic. `model_evaluation.py` adds archetype ranking, correlation and perturbation checks | Retrain with `retarget_dataset()` on real SAS-SV labels |
| Synthetic logs are cleaner than phone logs | Real logs have missing and duplicate events, timezone changes and restarts | The data-quality stage is exercised on real device logs during the pilot |
| Five archetypes are separable | Real usage varies continuously per person | Unsupervised clustering on pilot data, used descriptively and checked against SAS-SV |

The pilot is the next phase of the plan: M8 backend, M9 Android
collector, then data collection and analysis.

### Two design decisions resolved on paper ahead of their milestone

**Permission denial (designed for M9):** Android's
`PACKAGE_USAGE_STATS` permission requires explicit user action and
can be revoked at any time. The intended behavior, decided now so
M9's implementation has a target rather than discovering this
mid-build: if permission is denied or revoked, the Android app shows
an explicit "usage access needed" state (not a silent zero-data
result), and the backend distinguishes "no data because permission
was never granted" from "no data because nothing happened" — the
latter is what `assess_day_completeness()`'s gap heuristic already
partially addresses; the former needs an explicit signal from the
client, which M9 adds.

**Privacy architecture (for M8/M9):** since
this project analyzes behavioral patterns rather than generic app
metadata, an explicit position is stated now rather than left
implicit:
- What leaves the phone: session-level events (app, start/end time,
  category), not raw screen content or keystrokes.
- What is stored: M8's `storage/` (SQLite) holds it; `mock_backend`
  keeps nothing beyond a request.
- Retention and deletion: decided before M8's storage layer is built.
- On-device-only operation: an alternative to server-side scoring to
  evaluate during M8/M9.



Every milestone from M4 onward should add:
1. The actual model/logic in `src/attention_tracker/`
2. A corresponding field on `mock_backend`'s `SimulateDayResponse`
3. A corresponding section in the Android dashboard

This file's "Data flow" diagram and "Module reference" section should
be updated in the same pass — not left to drift until the whole
project looks different from what's documented here.