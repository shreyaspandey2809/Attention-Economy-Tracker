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

## Data flow, end to end (current state: M1–M3 complete)

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
                                  ▼
                     ┌─────────────────────────┐
                     │  group_sessions_by_      │   (pipeline/windowing.py)
                     │  user_app_day()          │
                     └────────────┬─────────────┘
                                  │  dict[(user, app, day), list[Session]]
                                  ▼
                     ┌─────────────────────────┐
                     │  build_feature_vector()  │   (pipeline/features/feature_vector.py)
                     │  — calls, per group:     │
                     │    volume.py             │
                     │    compulsiveness.py     │
                     │    temporal.py           │
                     │    transitions.py        │
                     └────────────┬─────────────┘
                                  │  FeatureVector (one per user/app/day)
                                  ▼
                     ┌─────────────────────────┐
                     │  mock_backend/main.py    │   FastAPI: POST /simulate-day
                     │  (demo layer, not M8)    │
                     └────────────┬─────────────┘
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
- **`temporal.py`** — `late_night_usage_pct` (23:00–04:00, matching
  the generator's own late-night window definition exactly),
  `hourly_usage_entropy` (Shannon entropy over hour-of-day, normalized
  to [0,1]), `weekend_usage_ratio` (duration-weighted, not
  count-weighted). Depends on `schema/session.py` only.
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

### `mock_backend/` — demo integration layer (not the real M8 backend)

- **`main.py`** — FastAPI service. `GET /archetypes` lists the real
  registered archetypes; `POST /simulate-day` runs
  `SyntheticEventGenerator` → `run_data_quality_pipeline` →
  `group_sessions_by_user_app_day` → `build_feature_vector`, and
  returns the result as JSON. No persistence — nothing is stored
  between requests. Depends on `synthetic/generator.py`,
  `synthetic/archetypes.py`, `pipeline/quality/pipeline.py`,
  `pipeline/windowing.py`, `pipeline/features/feature_vector.py`,
  `schema/taxonomy_loader.py`.

### `attention-collector-android/` — demo Android client (not the real M9 collector)

Kotlin + Jetpack Compose app. Archetype picker → "Simulate a day" →
calls `mock_backend`'s `POST /simulate-day` via Retrofit/Moshi →
displays the returned `FeatureVector` fields on a dashboard, with a
visually separate "Scoring & Explainability — in progress" panel for
M4–M7 output that doesn't exist yet. Does not read real on-device
usage data — see "What's a stand-in" below.

### Reserved, not yet implemented

These packages exist as empty scaffolding (`__init__.py` only) for
future milestones. Listed here so their emptiness reads as
intentional, not abandoned:

- **`scoring/`** — M4 (heuristic baseline), part of M5
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
- **Scoring.** Addiction/distraction scores, LightGBM/LSTM/autoencoder
  output, and SHAP explanations don't exist yet (M4–M7). The Android
  app's scoring panel is deliberately left visibly incomplete rather
  than showing placeholder numbers.

## Standing rule: keep the app in sync with the pipeline

Every milestone from M4 onward should add:
1. The actual model/logic in `src/attention_tracker/`
2. A corresponding field on `mock_backend`'s `SimulateDayResponse`
3. A corresponding section in the Android dashboard

This file's "Data flow" diagram and "Module reference" section should
be updated in the same pass — not left to drift until the whole
project looks different from what's documented here.