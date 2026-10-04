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

## Status

M1–M5 complete; 322 automated tests pass. All data so far is synthetic.
Full history: [`CHANGELOG.md`](CHANGELOG.md).

| Milestone | Status |
|---|---|
| M1 Schema layer | done |
| M2 Synthetic generator (5 archetypes) | done |
| M3 Sessions, data quality, features | done |
| M4 Heuristic scorer | done |
| M5 LightGBM addiction + distraction models | done |
| M6 LSTM + autoencoder | not started |
| M7 SHAP explainability | not started |
| M8 Backend + SQLite | not started |
| M9 Android collection | not started |
| M10 Dashboard | not started |

**Validation status.** Scores are computed from synthetic usage, since
no real-device data has been collected yet. The heuristic is
expert-weighted and the M5 models are distilled from it, so their fit
measures how closely they reproduce the heuristic, not real-world
accuracy. Validation against real users (SAS-SV self-report pilot) is
the next phase; the protocol and statistics are already built and
tested: [`docs/validation_protocol.md`](docs/validation_protocol.md).
Design notes and scope: [`docs/architecture.md`](docs/architecture.md).

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
ruff check src tests mock_backend
```

Install with `pip install -e ".[test]"` to get everything the tests need.

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