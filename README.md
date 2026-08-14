# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See `docs/architecture.md` (added later) for the full module map.
Build runs in four phases:

- **Phase 1 — Data foundation:** schema, synthetic data generation,
  session joining, feature engineering, heuristic baseline (M1-M4)
- **Phase 2 — ML core:** LightGBM addiction + distraction models,
  LSTM sequence model, autoencoder, SHAP explainability (M5-M7)
- **Phase 3 — Backend + database:** SQLite storage, FastAPI serving
  layer, config migration (M8)
- **Phase 4 — Android + frontend:** on-device collector, React
  dashboard (M9-M10)

## Status: Phase 1 — Data Foundation (in progress)

- [x] M1: Schema Layer — `RawEvent`, `Session`, `AppMetadataEntry`,
      `TaxonomyLoader` + 50-app seed taxonomy
- [x] M2: Synthetic Data Generator — all 4 archetypes (`BALANCED`,
      `DOOMSCROLLER`, `BINGE_WEEKEND`, `DEEP_WORKER`) + population
      generation
- [x] M3 (started): `SessionBuilder` — joins OPENED/CLOSED event pairs
      into `Session` records via FIFO pairing per (user, package), and
      assigns `transition_from` / `transition_to` from each user's
      chronological session order. Unmatched opens/closes (e.g. a
      session still running at the end of a window) are returned for
      inspection rather than silently dropped or raised as errors.
- [x] **Bugfix found during Session Builder testing:** the synthetic
      generator (M2) could produce overlapping sessions — two
      sessions, even of different apps, occupying intersecting time
      ranges — which is physically impossible on a real device (only
      one app can be in the foreground at a time) and broke the
      Session Builder's pairing. Fixed by clamping each session's
      start time against a running cursor, threaded across day
      boundaries so late-night sessions can't collide with the next
      day's sessions either. Verified with a 200-seed × 4-archetype ×
      30-day stress check (427,739 adjacent-session pairs, zero
      overlaps) beyond the committed test suite.
- [x] Unit tests: 71 passing total
- [ ] M3 (remaining): Feature Pipeline — volume, compulsiveness,
      temporal, and transition features
- [ ] M4: Heuristic Baseline scorer

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
src/attention_tracker/   # all package code, organized by module (M1-M10)
tests/                   # mirrors src/ — one test module per source module
config/                  # YAML configs, populated during Phase 3 (Ch. 9.2)
android/                 # Android collector (Phase 4)
dashboard/               # React dashboard (Phase 4)
```

## Try it yourself

```python
from datetime import datetime, timezone
from attention_tracker.synthetic.archetypes import BALANCED, DOOMSCROLLER
from attention_tracker.synthetic.generator import SyntheticEventGenerator

gen = SyntheticEventGenerator()
events = gen.generate(
    user_id="demo_user",
    profile=DOOMSCROLLER,
    start_date=datetime(2026, 8, 3, tzinfo=timezone.utc),
    num_days=7,
)
print(f"Generated {len(events)} events across 7 days")
```