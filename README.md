# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See `docs/architecture.md` (added later) for the full module map.
This repo follows the staged build plan: M1 (schema) → M2 (synthetic
data) → M3 (sessions + features) → M4 (heuristic baseline) → M5
(LightGBM models) → M6 (LSTM + autoencoder) → M7 (SHAP) → M8 (FastAPI)
→ M9 (Android) → M10 (dashboard).

## Status: Week 3 — Synthetic Generator started (M2 in progress)

- [x] M1: Schema Layer — `RawEvent`, `Session`, `AppMetadataEntry`,
      `TaxonomyLoader` + 50-app seed taxonomy (Weeks 1-2)
- [x] `ArchetypeProfile` — declarative behavioral profile (category
      weights, session duration/count distributions, late-night
      fraction, same-category continuation probability)
- [x] `BALANCED` and `DOOMSCROLLER` archetypes defined
- [x] `SyntheticEventGenerator` — turns a profile into a chronologically
      sorted, schema-valid `RawEvent` stream for N simulated days
- [x] Unit tests: 42 passing total (32 schema + 10 new). Includes
      structural validity checks (every event is a real, validated
      RawEvent; OPENED/CLOSED pairs match) AND archetype-separation
      checks (Doomscroller shows more addictive-category time,
      more late-night sessions, and longer average sessions than
      Balanced on the same seed — confirming the archetypes are
      behaviorally distinguishable, which M5's model evaluation
      later depends on)
- [ ] Binge Weekend, Deep Worker archetypes + configurable
      population/time window (Week 4, next up)

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