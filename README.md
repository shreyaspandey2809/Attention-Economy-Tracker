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
- [x] M3 (in progress): `SessionBuilder` — joins OPENED/CLOSED event
      pairs into `Session` records via FIFO pairing per (user,
      package), with `transition_from` / `transition_to` from each
      user's chronological session order
- [x] **Bugfix found during Session Builder testing:** the synthetic
      generator (M2) could produce overlapping sessions — physically
      impossible on a real device (only one app can be in the
      foreground at a time). Fixed by clamping start times against a
      running cursor, threaded across day boundaries. Verified with a
      200-seed × 4-archetype × 30-day stress check (427,739
      adjacent-session pairs, zero overlaps).
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
- [x] Unit tests: 100 passing total
- [ ] M3 (remaining): Temporal features (`late_night_usage_pct`,
      `hourly_usage_entropy`), Transition features, and
      `feature_vector.py` assembly
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