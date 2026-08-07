# Attention Economy Tracker

Behavioral analytics system for smartphone app usage — scores per-app
"addiction" and "distraction" using engineered features + LightGBM,
with a synthetic-data-first, backend-first build order.

See `docs/architecture.md` (added later) for the full module map.
This repo follows the staged build plan: M1 (schema) → M2 (synthetic
data) → M3 (sessions + features) → M4 (heuristic baseline) → M5
(LightGBM models) → M6 (LSTM + autoencoder) → M7 (SHAP) → M8 (FastAPI)
→ M9 (Android) → M10 (dashboard).

## Status: Week 2 — Schema Layer complete (M1 done)

- [x] `RawEvent` Pydantic model with tz-aware timestamp enforcement
      and terminal-event field validation (Week 1)
- [x] `AppCategory` enum (Week 1)
- [x] `Session` model — joined start/end event pair, with
      timestamp-vs-duration consistency validation and transition
      fields (`transition_from` / `transition_to`) for M3's later use
- [x] `AppMetadataEntry` model + `TaxonomyLoader` — loads and
      validates `config/app_taxonomy.yaml` (50 seed apps across all 5
      categories), with graceful `UNKNOWN`-category fallback for
      unlisted packages rather than raising
- [x] Unit tests: 32 passing total (14 schema + 18 new — Session
      validation, taxonomy loading, malformed-file handling)
- [ ] M2: Synthetic Data Generator — archetypes + event stream
      (Weeks 3-4, next up)

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
