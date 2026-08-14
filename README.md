# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See `docs/architecture.md` (added later) for the full module map.
This repo follows the staged build plan: M1 (schema) → M2 (synthetic
data) → M3 (sessions + features) → M4 (heuristic baseline) → M5
(LightGBM models) → M6 (LSTM + autoencoder) → M7 (SHAP) → M8 (FastAPI)
→ M9 (Android) → M10 (dashboard).

## Status: Week 5 — Session Builder complete (M3 started)

- [x] M1: Schema Layer (Weeks 1-2)
- [x] M2: Synthetic Data Generator — all 4 archetypes + population
      generation (Weeks 3-4)
- [x] `SessionBuilder` — joins OPENED/CLOSED event pairs into
      `Session` records via FIFO pairing per (user, package), and
      assigns `transition_from` / `transition_to` from each user's
      chronological session order. Unmatched opens/closes (e.g. a
      session still running at the end of a window) are returned for
      inspection rather than silently dropped or raised as errors.
- [x] **Bugfix found via Week 5 testing:** the synthetic generator
      (M2) could produce overlapping sessions — two sessions, even of
      different apps, occupying intersecting time ranges — which is
      physically impossible on a real device (only one app can be in
      the foreground at a time) and broke the Session Builder's
      pairing. Fixed by clamping each session's start time against a
      running cursor, threaded across day boundaries so late-night
      sessions can't collide with the next day's sessions either.
      Verified with a 200-seed × 4-archetype × 30-day stress check
      (427,739 adjacent-session pairs, zero overlaps) beyond the
      committed test suite.
- [x] Unit tests: 71 passing total (58 prior + 13 new — session
      pairing, transition assignment, multi-user isolation, unmatched-
      event handling, FIFO-under-rapid-reopen, full round-trip against
      the synthetic generator, plus a generator-level non-overlap
      regression test)
- [ ] Feature Pipeline — volume + compulsiveness features (Week 8,
      after Week 6 continues M3/M4 groundwork)

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