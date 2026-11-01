"""Scoring job: raw events in the database -> sessions, features, scores.

Runs the existing, unchanged pipeline for one user over *all* of that user's
stored events (sessions can straddle midnight and dedup/pairing are
stream-level, so partial re-runs would be wrong), then rebuilds the derived
tables for that user in one transaction. Raw events are never modified.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from attention_tracker.models.dataset import feature_row
from attention_tracker.models.registry import ModelRecord, latest_record, load_model
from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.completeness import assess_day_completeness
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.distraction import compute_distraction_score
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.storage.repository import DailyRow, Repository, WindowRow

log = logging.getLogger(__name__)

MODEL_KINDS: tuple[str, ...] = ("addiction", "distraction")


def clamp_score(x: float) -> float:
    return max(0.0, min(10.0, x))


@dataclass(frozen=True)
class ScoreSummary:
    user_id: str
    sessions: int
    windows: int
    days: int
    model_versions: dict[str, str]


class ModelCache:
    """Latest registry model per kind. A model trained while the server runs is
    picked up on the next scoring run (the cached one is dropped when the
    latest version string changes). Unloadable models mean heuristic-only."""

    def __init__(self, model_dir: Path | str | None = None):
        self.model_dir = Path(model_dir) if model_dir is not None else None
        self._loaded: dict[str, tuple[object, ModelRecord]] = {}

    def current(self) -> dict[str, tuple[object, ModelRecord]]:
        out: dict[str, tuple[object, ModelRecord]] = {}
        for kind in MODEL_KINDS:
            record = latest_record(kind, self.model_dir)  # type: ignore[arg-type]
            if record is None:
                self._loaded.pop(kind, None)
                continue
            cached = self._loaded.get(kind)
            if cached is None or cached[1].version != record.version:
                try:
                    self._loaded[kind] = (load_model(record.path), record)
                except (ValueError, ImportError, OSError) as exc:
                    log.warning("cannot load %s model %s: %s", kind, record.version, exc)
                    self._loaded.pop(kind, None)
                    continue
            out[kind] = self._loaded[kind]
        return out

    def versions(self) -> dict[str, str]:
        return {kind: record.version for kind, (_m, record) in self.current().items()}


class ScoringJob:
    def __init__(self, repo: Repository, taxonomy: TaxonomyLoader, model_cache: ModelCache | None = None):
        self.repo = repo
        self.taxonomy = taxonomy
        self.models = model_cache or ModelCache()

    def category_for(self, package_name: str):
        override = self.repo.category_override(package_name)
        return override if override is not None else self.taxonomy.lookup(package_name).category

    def ensure_scored(self, user_id: str) -> bool:
        """Re-score the user if events arrived since the last run. True when a run happened."""
        with self.repo.db.lock:  # check + run atomically w.r.t. concurrent ingest
            user = self.repo.get_user(user_id)
            if user is None or not user["scores_stale"]:
                return False
            self.score_user(user_id)
            return True

    def score_stale_users(self) -> list[ScoreSummary]:
        return [self.score_user(uid) for uid in self.repo.stale_user_ids()]

    def score_user(self, user_id: str) -> ScoreSummary:
        # Hold the DB lock across load -> compute -> replace so an ingest that lands
        # mid-run cannot have its `stale` flag cleared by this run's commit.
        with self.repo.db.lock:
            events = self.repo.load_events(user_id)
            result = run_data_quality_pipeline(events, taxonomy=self.taxonomy)
            sessions = result.sessions

            keyed = []
            for (_u, _pkg, day), group in group_sessions_by_user_app_day(sessions).items():
                fv = build_feature_vector(group, self.taxonomy)
                keyed.append((day, fv, self.category_for(fv.package_name)))

            models = self.models.current()
            rows = [feature_row(fv, cat) for _d, fv, cat in keyed]
            model_scores: dict[str, list[float]] = {
                kind: [clamp_score(p) for p in model.predict(rows)]  # type: ignore[attr-defined]
                for kind, (model, _rec) in models.items()
            }

            windows: list[WindowRow] = []
            for i, (day, fv, cat) in enumerate(keyed):
                windows.append(
                    WindowRow(
                        day=day,
                        features=fv,
                        category=cat,
                        heuristic_score=compute_heuristic_score(fv, cat),
                        distraction_score=compute_distraction_score(fv, cat),
                        addiction_model_score=model_scores["addiction"][i] if "addiction" in models else None,
                        distraction_model_score=model_scores["distraction"][i] if "distraction" in models else None,
                        addiction_model_version=models["addiction"][1].version if "addiction" in models else None,
                        distraction_model_version=models["distraction"][1].version if "distraction" in models else None,
                    )
                )

            daily = _daily_rows(windows, sessions)
            self.repo.replace_derived(user_id, sessions, windows, daily)

        return ScoreSummary(
            user_id=user_id,
            sessions=len(sessions),
            windows=len(windows),
            days=len(daily),
            model_versions={k: rec.version for k, (_m, rec) in models.items()},
        )


def _weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    """Mean of values weighted by seconds; plain mean when every weight is 0."""
    if not pairs:
        return None
    total_w = sum(w for _v, w in pairs)
    if total_w <= 0:
        return sum(v for v, _w in pairs) / len(pairs)
    return sum(v * w for v, w in pairs) / total_w


def _daily_rows(windows: list[WindowRow], sessions: list[Session]) -> list[DailyRow]:
    by_day: dict[date, list[WindowRow]] = defaultdict(list)
    for w in windows:
        by_day[w.day].append(w)
    sessions_by_day: dict[date, list[Session]] = defaultdict(list)
    for s in sessions:
        sessions_by_day[s.local_start_time.date()].append(s)

    out = []
    for day in sorted(by_day):
        ws = by_day[day]
        weight = lambda w: w.features.total_time_sec  # noqa: E731
        completeness = assess_day_completeness(sessions_by_day[day])
        out.append(
            DailyRow(
                day=day,
                total_time_sec=sum(weight(w) for w in ws),
                heuristic_score=_weighted_mean([(w.heuristic_score, weight(w)) for w in ws]),  # type: ignore[arg-type]
                distraction_score=_weighted_mean([(w.distraction_score, weight(w)) for w in ws]),  # type: ignore[arg-type]
                addiction_model_score=_weighted_mean(
                    [(w.addiction_model_score, weight(w)) for w in ws if w.addiction_model_score is not None]
                ),
                distraction_model_score=_weighted_mean(
                    [(w.distraction_model_score, weight(w)) for w in ws if w.distraction_model_score is not None]
                ),
                is_complete=completeness.is_complete,
                max_gap_hours=completeness.max_gap_hours,
                completeness_reason=completeness.reason,
            )
        )
    return out
