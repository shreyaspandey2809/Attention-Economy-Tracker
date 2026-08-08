# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See `docs/architecture.md` (added later) for the full module map.
This repo follows the staged build plan: M1 (schema) → M2 (synthetic
data) → M3 (sessions + features) → M4 (heuristic baseline) → M5
(LightGBM models) → M6 (LSTM + autoencoder) → M7 (SHAP) → M8 (FastAPI)
→ M9 (Android) → M10 (dashboard).

## Status: Week 4 — Synthetic Generator complete (M2 done)

- [x] M1: Schema Layer (Weeks 1-2)
- [x] `BALANCED`, `DOOMSCROLLER` archetypes + core generator (Week 3)
- [x] `BINGE_WEEKEND`, `DEEP_WORKER` archetypes (Week 4)
- [x] `ArchetypeProfile` extended with `weekend_session_multiplier` /
      `weekend_duration_multiplier` — generator now varies session
      count and duration by weekday vs weekend per-archetype
- [x] `generate_population()` — generates events for many users at
      once, each under a (possibly different) archetype
- [x] `build_population_spec()` — builds a population dict from
      `[(profile, count), ...]` pairs, with self-documenting user_ids
      (e.g. `user_DOOMSCROLLER_003`)
- [x] `flatten_population()` — merges a population's events into one
      chronologically sorted stream, simulating multi-device ingestion
- [x] Unit tests: 58 passing total (48 prior + 10 new). Covers
      structural validity for both new archetypes, weekend-multiplier
      effect (same seed, weekday vs Saturday, confirms the split is
      real), Deep Worker vs Doomscroller category-composition
      separation, and population-generation correctness
- [ ] M3: Session Builder — join OPENED/CLOSED into Session records
      (Week 7, next up after Month 2 continues)

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
config/                  # YAML configs, populated starting Month 6 (Ch. 9.2)
android/                 # Android collector (M9, starts Month 6)
dashboard/               # React dashboard (M10, starts Month 7)
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