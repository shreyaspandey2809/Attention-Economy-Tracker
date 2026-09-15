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

## Data flow, end to end (current state: M1–M4 complete)

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
tested (158 tests as of M3 completion). `mock_backend` and the Android
app are demo/integration layers — they call the real pipeline but are
not themselves M8 or M9's actual scope (see "What's a stand-in" below).

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
- **`app_metadata.py`** — `AppCategory` enum (PRODUCTIVE, ADDICTIVE,
  ENTERTAINMENT, COMMUNICATION, UTILITY, UNKNOWN).
- **`app_metadata_entry.py`** — `AppMetadataEntry`, the validated shape
  of one taxonomy row (imports `app_metadata.py`).
- **`taxonomy_loader.py`** — `TaxonomyLoader`, reads
  `config/app_taxonomy.yaml` and exposes `.lookup(package_name)`,
  falling back to `AppCategory.UNKNOWN` for unrecognized packages
  rather than raising (imports `app_metadata.py`,
  `app_metadata_entry.py`).

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
  `synthetic/archetypes.py`.

### `pipeline/quality/` — cleans the raw event/session stream

- **`dedup.py`** — `dedupe_events()`. Removes duplicate `RawEvent`s:
  `session_id` as idempotency key for terminal events, exact
  `(user_id, package_name, timestamp)` match for opening events that
  have none yet. Depends on `schema/raw_event.py` only.
- **`outliers.py`** — `cap_session_outliers()`. Caps session durations
  at a device-plausibility bound (`MAX_PLAUSIBLE_SESSION_SEC`, 4
  hours) rather than a statistical percentile, so genuine heavy-usage
  days aren't clipped alongside measurement errors. Depends on
  `schema/session.py` only.
- **`pipeline.py`** — `run_data_quality_pipeline()`. The orchestration
  point: dedup → `SessionBuilder.build()` → outlier capping, in that
  fixed order, as one callable. This is the only place that ordering
  logic lives; every other caller (the demo script, `mock_backend`)
  calls this function rather than re-chaining the three stages.
  Depends on `dedup.py`, `outliers.py`, `pipeline/session_builder.py`,
  `schema/raw_event.py`, `schema/session.py`.
- **`completeness.py`** — `assess_day_completeness()`. A **documented
  placeholder heuristic**: flags a user's day as suspicious if the
  largest session-free gap (across ALL the user's apps, not one)
  exceeds a threshold (default 6 hours). Cannot distinguish a real
  sync failure from genuine non-use — that distinction needs M9's
  Android sync heartbeat, which doesn't exist yet. Takes the full
  `list[Session]` for one user-day (not a
  `group_sessions_by_user_app_day()` output, which is scoped to one
  app). Depends on `schema/session.py` only.

### `pipeline/` (top level) — turns events into sessions, sessions into windows

- **`session_builder.py`** — `SessionBuilder`. FIFO-pairs OPENED with
  CLOSED/BACKGROUND events per `(user_id, package_name)`, and computes
  `transition_from`/`transition_to` per user across ALL apps
  chronologically (not per-window — this is why
  `productive_interruption_rate` can read a pre-computed value rather
  than needing cross-window context itself). Depends on
  `schema/raw_event.py`, `schema/session.py`.
- **`windowing.py`** — `group_sessions_by_user_app_day()`. Groups a
  flat `list[Session]` into `dict[(user, package, day), list[Session]]`,
  pre-sorted by `start_time` within each group. Depends on
  `schema/session.py` only.

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
  duration-weighted counterpart, added as a fix for a weakness noted
  in external review — see "Known limitations" below — both are kept
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

### `scoring/` — M4 heuristic baseline (M5's `models/` still reserved)

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
  explicit input (not looked up internally) to apply a
  `productive_app_dampener` — the fix for the `DEEP_WORKER` finding
  above. This score is the M5 LightGBM training TARGET, since no true
  ground-truth addiction label exists. Depends on
  `pipeline/features/feature_vector.py`, `schema/app_metadata.py`,
  `scoring/config.py`.
  **Validation:** archetype-ordering only (no ground truth exists) —
  see `tests/scoring/test_heuristic.py`, run across all five
  archetypes and 30 seeds each at a 27/30 pass-rate bar, matching the
  rigor used for the M3 interarrival-statistic fix.

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
  `schema/taxonomy_loader.py`.

### `attention-collector-android/` — demo Android client (not the real M9 collector)

Kotlin + Jetpack Compose app. Archetype picker → "Simulate a day" →
calls `mock_backend`'s `POST /simulate-day` via Retrofit/Moshi →
displays the returned `FeatureVector` fields plus each app's
`heuristic_score` (M4, shown as a colored 0-10 badge on each app
card) and the day's completeness assessment, with a visually separate
"Model-based scoring — still in progress" panel for M5–M7 output that
doesn't exist yet. Does not read real on-device usage data — see
"What's a stand-in" below.

### Reserved, not yet implemented

These packages exist as empty scaffolding (`__init__.py` only) for
future milestones. Listed here so their emptiness reads as
intentional, not abandoned:

- **`models/`** — M5 (LightGBM), M6 (LSTM, autoencoder)
- **`explainability/`** — M7 (SHAP)
- **`storage/`** — M8 (SQLite persistence)
- **`api/`** — M8 (the real FastAPI service, replacing `mock_backend`)
- **`utils/`** — cross-cutting helpers, populated as needed rather
  than on a fixed milestone

## What's a stand-in, and what's real

It's easy to misread `mock_backend/` and the Android app as "fake" —
they're not. Every computation between `SyntheticEventGenerator` and
the JSON response is the real, tested pipeline code from `src/`.
What's *not* real yet:

- **The data source.** `mock_backend` calls `SyntheticEventGenerator`,
  not a real device. The Android app's "Simulate a day" button
  fabricates a day's usage from an archetype's statistics — it does
  not read `UsageStatsManager` or anything else from the phone it
  runs on. Real collection is M9's scope.
- **Persistence.** `mock_backend` holds nothing between requests — no
  database, no history. That's M8's `storage/` scope.
- **Model-based scoring.** LightGBM/LSTM/autoencoder output and SHAP
  explanations don't exist yet (M5–M7). The M4 heuristic score IS
  real (see `scoring/heuristic.py`) — it's a real, tested, weighted
  combination of real features, not a fabricated number — but it's a
  hand-designed heuristic, not a learned model. The Android app's
  "Model-based scoring" panel is deliberately left visibly incomplete
  for the M5-M7 pieces rather than showing placeholder numbers.
- **Completeness.** `assess_day_completeness()` is a real, tested gap
  heuristic, but it genuinely cannot distinguish a sync failure from
  the user simply not using their phone — that requires M9's Android
  sync heartbeat, which doesn't exist yet. Treat an "incomplete" flag
  as "worth a closer look," not as a confirmed sync problem.

## Known limitations

An external review of this project's methodology raised 37 numbered
weaknesses, spanning validity, feature design, data, Android, backend,
and testing concerns. Most were either already-planned future
milestones (Android/backend items — see "What's a stand-in" above) or
concrete engineering fixes (addressed directly in `scoring/config.py`,
`pipeline/features/temporal.py`, and `tests/scoring/`). A subset,
however, are structural limitations of building on synthetic data
with no real-user labels — no amount of additional code resolves
them, only real behavioral data with independently-obtained labels
can. Documenting them precisely, rather than leaving them
unaddressed, is the correct response to this category:

- **No ground-truth labels exist.** There is no validated definition
  of "problematic attention behavior" this project's score is checked
  against, and no real-human-outcomes dataset to calibrate it with.
  A score of 7 does not have an established real-world meaning.
- **The heuristic weights are expert-chosen, not learned.** See
  `scoring/config.py`'s "WEIGHT PROVENANCE" section for the full
  statement — this is written directly into the code, not only here.
- **Circular validation.** The synthetic archetypes (`DOOMSCROLLER`,
  `COMPULSIVE_CHECKER`, etc.) are constructed to exhibit the exact
  behaviors the scorer is designed to detect, and the scorer is then
  checked against those same constructed behaviors. This validates
  internal consistency (does the code do what it was designed to do)
  but not correspondence to real human behavior.
- **M5's LightGBM models will learn the heuristic, not reality.**
  Since M4's score is the only available training target, a high
  model accuracy will demonstrate that LightGBM can approximate the
  hand-designed formula — not that either the heuristic or the model
  detects real addictive behavior.
- **No independent validation dataset.** There is no held-out,
  real-user, independently-labeled dataset to measure generalization
  against.
- **Synthetic data is cleaner than real smartphone data.** Real usage
  logs contain missing events, duplicated events, ambiguous
  transitions, timezone changes, and device restarts in combinations
  the synthetic generator does not attempt to reproduce. The
  data-quality stage (dedup, outlier capping, completeness) is
  designed against the failure modes the team anticipated, not
  against an exhaustive real-world sample.
- **Archetypes are more separable than real people.** Real usage
  likely varies continuously and inconsistently per person, not
  cleanly into five categories.

**What would actually resolve this category:** a small pilot with
real users and an independently-collected behavioral or self-report
label (or comparison against an existing public dataset with such
labels), used to check whether the heuristic's relative ordering and
M5's learned model hold up against real outcomes — not just against
the synthetic archetypes that were used to build them. This is
tracked as a known gap, not a blocker to continuing the engineering
build in the meantime.

### Two design decisions resolved on paper ahead of their milestone

**Permission denial (relevant to M9, not yet built):** Android's
`PACKAGE_USAGE_STATS` permission requires explicit user action and
can be revoked at any time. The intended behavior, decided now so
M9's implementation has a target rather than discovering this
mid-build: if permission is denied or revoked, the Android app shows
an explicit "usage access needed" state (not a silent zero-data
result), and the backend distinguishes "no data because permission
was never granted" from "no data because nothing happened" — the
latter is what `assess_day_completeness()`'s gap heuristic already
partially addresses; the former needs an explicit signal from the
client, which does not exist yet since M9 hasn't started.

**Privacy architecture (relevant to M8/M9, not yet built):** since
this project analyzes behavioral patterns rather than generic app
metadata, an explicit position is stated now rather than left
implicit:
- What leaves the phone: session-level events (app, start/end time,
  category), not raw screen content or keystrokes.
- What is stored: to be implemented in M8 (`storage/`, SQLite) — not
  yet built, so nothing is currently stored beyond a single request's
  lifetime in `mock_backend`.
- Retention and deletion: not yet designed — this should be decided
  before M8's storage layer is implemented, not after.
- On-device-only operation: not currently supported and not yet
  evaluated as an alternative to server-side scoring; noted here as
  an open question for M8/M9 rather than a resolved "no."



Every milestone from M4 onward should add:
1. The actual model/logic in `src/attention_tracker/`
2. A corresponding field on `mock_backend`'s `SimulateDayResponse`
3. A corresponding section in the Android dashboard

This file's "Data flow" diagram and "Module reference" section should
be updated in the same pass — not left to drift until the whole
project looks different from what's documented here.