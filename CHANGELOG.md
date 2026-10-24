# Changelog

Newest first.

## Phase 1 — M5 complete (Oct 2026)

- Added: a separate distraction heuristic (`scoring/distraction.py`).
  The distraction model trains on its own target; its Spearman
  correlation with the addiction heuristic is about 0.70 on the default
  synthetic dataset. `Dataset` gained an optional `distraction_targets`.
- Added: model registry (`models/registry.py`) with versioned save/load
  and a `meta.json` per model, plus
  `python -m attention_tracker.models.train_cli`. Registry output is
  git-ignored.
- Added: `mock_backend` returns `distraction_score`,
  `addiction_model_score`, `distraction_model_score` and
  `model_versions`; `scoring_status` is `models_loaded` when both models
  exist. The Android dashboard shows both heuristic badges and the model
  scores.
- Changed: both models read all 18 columns and differ by target.
- Tests: 346 pass.

## Phase 0 — reproducibility and tooling (Oct 2026)

- Added: deterministic synthetic dataset across processes (per-user RNG
  seeded with `zlib.crc32`), with a cross-process test under different
  `PYTHONHASHSEED` values.
- Added: `pyyaml` to `pyproject.toml`, so `pip install -e .` works in a
  clean environment.
- Added: a group-aware train / validation / test split in
  `train_model()`. Early stopping watches validation only and the test
  split is report-only. `TrainResult` gained `val_distillation` and
  `best_iteration`; early stopping ends training at about 230 rounds.
  Test R² against the heuristic: addiction 0.989, distraction 0.981.
- Added: a minimal ruff config in `pyproject.toml`.

## Milestones M1–M5

### M5 — LightGBM addiction and distraction models
- `dataset.py`: 18-column feature rows (12 engineered features + 6
  one-hot categories); undefined features are NaN, never 0.
- `synthetic_dataset.py`: one synthetic user per (archetype, seed),
  run through the real pipeline.
- `lightgbm_scorer.py`: user-grouped splits, early stopping,
  `retarget_dataset()` for swapping in real SAS-SV labels.
- `model_evaluation.py`: archetype-ranking check on held-out users,
  Spearman correlation against the heuristic, and stability under input
  noise. On the default configuration the test split reaches R² of about
  0.98-0.99, rho about 0.995, and the archetype ordering holds at every
  noise level tried.
- Every `DistillationReport` carries a caveat: the figures measure
  agreement with the heuristic on synthetic users.
- 35 tests.

### M4 — Heuristic baseline
- `scoring/heuristic.py`: weighted 0-10 score over eight normalized
  features, with a productive-app dampener and category multipliers.
- A weight-sensitivity suite perturbs each of the 8 weights by ±25%; the
  archetype ordering held in all 16 perturbations.
- Archetype-ordering test across five archetypes and 30 seeds each.

### M3 — Sessions, data quality and features
- Session builder: FIFO open/close pairing, transitions, local-time
  handling; pairs that fail validation are recorded in `rejected_pairs`.
- Data-quality stage: dedup, 4-hour outlier cap, overlap detection,
  day-completeness assessment.
- Features: volume, compulsiveness (inter-arrival and short-session
  ratios), temporal (late-night share by count and by duration, hourly
  entropy, weekend ratio) and transitions (productive interruption
  rate), assembled into `FeatureVector`.
- Synthetic generator keeps one foreground app at a time, verified over
  200 seeds × 4 archetypes × 30 days (427,739 adjacent session pairs,
  zero overlaps).
- Inter-arrival behavior is tested on pooled gaps across a 15-user
  population (stable across 50/50 seeds).
- Feature-correlation measurements recorded in `scoring/config.py`.
- 283 tests at the end of M4.

### M2 — Synthetic generator
- Five archetypes: `BALANCED`, `DEEP_WORKER`, `DOOMSCROLLER`,
  `BINGE_WEEKEND`, `COMPULSIVE_CHECKER`.
- Seedable event generator with timezone offsets and a late-night
  window.

### M1 — Schema layer
- `RawEvent`, `Session`, `AppMetadataEntry`, `AppCategory`, YAML
  taxonomy loader (seed and extended taxonomies).

### Demo layer
- `mock_backend/` (FastAPI) and the Kotlin/Compose Android client run
  the real pipeline end to end. A standing rule: each milestone from M4
  adds a field to `/simulate-day` and a matching dashboard section.