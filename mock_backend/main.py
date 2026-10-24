from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from attention_tracker.models.dataset import feature_row
from attention_tracker.models.registry import load_latest
from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.completeness import assess_day_completeness
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.distraction import compute_distraction_score
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.synthetic.archetypes import ARCHETYPES
from attention_tracker.synthetic.generator import SyntheticEventGenerator

app = FastAPI(title="Attention Economy Tracker — MOCK backend (demo only)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_generator = SyntheticEventGenerator()
_taxonomy = TaxonomyLoader()

# kind -> (model, registry record). Filled lazily; a model trained after the
# server started is picked up on the next request, no restart needed.
_models: dict = {}


def _get_models() -> dict:
    for kind in ("addiction", "distraction"):
        if kind not in _models:
            loaded = load_latest(kind)
            if loaded is not None:
                _models[kind] = loaded
    return _models


def _clamp_score(x: float) -> float:
    return max(0.0, min(10.0, x))


class SimulateDayRequest(BaseModel):
    archetype: str
    user_id: str = "demo_user"


class AppFeatureSummary(BaseModel):
    package_name: str

    session_count: int
    total_time_sec: float
    avg_session_duration_sec: float
    max_session_duration_sec: float

    interarrival_mean_sec: float | None
    sessions_under_30s_ratio: float
    interarrival_under_2min_ratio: float | None

    late_night_usage_pct: float
    late_night_usage_time_ratio: float
    hourly_usage_entropy: float
    weekend_usage_ratio: float

    productive_interruption_rate: float

    heuristic_score: float
    distraction_score: float
    # LightGBM predictions (M5). None when no trained model is in the registry.
    addiction_model_score: float | None = None
    distraction_model_score: float | None = None


class CompletenessSummary(BaseModel):
    is_complete: bool
    max_gap_hours: float
    reason: str


class SimulateDayResponse(BaseModel):
    archetype: str
    user_id: str
    raw_event_count: int
    duplicate_count: int
    session_count_total: int
    outliers_capped: int
    rejected_pairs_count: int
    overlapping_sessions_count: int
    completeness: CompletenessSummary
    per_app_features: list[AppFeatureSummary]
    scoring_status: str
    scoring_message: str
    # kind -> registry version of the model that produced the *_model_score fields.
    model_versions: dict[str, str] = {}


@app.get("/archetypes")
def list_archetypes() -> list[str]:
    return sorted(ARCHETYPES.keys())


@app.post("/simulate-day", response_model=SimulateDayResponse)
def simulate_day(req: SimulateDayRequest) -> SimulateDayResponse:
    profile = ARCHETYPES.get(req.archetype)
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown archetype '{req.archetype}'. "
            f"Valid options: {sorted(ARCHETYPES.keys())}",
        )

    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    events = _generator.generate(req.user_id, profile, day_start, num_days=1)
    quality_result = run_data_quality_pipeline(events)

    completeness_result = assess_day_completeness(quality_result.sessions)

    windows = group_sessions_by_user_app_day(quality_result.sessions)
    models = _get_models()
    per_app: list[AppFeatureSummary] = []
    for (user_id, package_name, day), sessions in windows.items():
        fv = build_feature_vector(sessions, _taxonomy)
        app_category = _taxonomy.lookup(fv.package_name).category
        score = compute_heuristic_score(fv, app_category)
        row = feature_row(fv, app_category)
        model_scores = {
            kind: _clamp_score(model.predict([row])[0])
            for kind, (model, _record) in models.items()
        }
        per_app.append(
            AppFeatureSummary(
                package_name=fv.package_name,
                session_count=fv.session_count,
                total_time_sec=fv.total_time_sec,
                avg_session_duration_sec=fv.avg_session_duration_sec,
                max_session_duration_sec=fv.max_session_duration_sec,
                interarrival_mean_sec=fv.interarrival_mean_sec,
                sessions_under_30s_ratio=fv.sessions_under_30s_ratio,
                interarrival_under_2min_ratio=fv.interarrival_under_2min_ratio,
                late_night_usage_pct=fv.late_night_usage_pct,
                late_night_usage_time_ratio=fv.late_night_usage_time_ratio,
                hourly_usage_entropy=fv.hourly_usage_entropy,
                weekend_usage_ratio=fv.weekend_usage_ratio,
                productive_interruption_rate=fv.productive_interruption_rate,
                heuristic_score=score,
                distraction_score=compute_distraction_score(fv, app_category),
                addiction_model_score=model_scores.get("addiction"),
                distraction_model_score=model_scores.get("distraction"),
            )
        )
    per_app.sort(key=lambda a: a.heuristic_score, reverse=True)

    return SimulateDayResponse(
        archetype=req.archetype,
        user_id=req.user_id,
        raw_event_count=len(events),
        duplicate_count=quality_result.dedup_result.duplicate_count,
        session_count_total=len(quality_result.sessions),
        outliers_capped=quality_result.outlier_result.capped_count,
        rejected_pairs_count=len(quality_result.build_result.rejected_pairs),
        overlapping_sessions_count=len(
            quality_result.outlier_result.overlapping_session_ids
        ),
        completeness=CompletenessSummary(
            is_complete=completeness_result.is_complete,
            max_gap_hours=completeness_result.max_gap_hours,
            reason=completeness_result.reason,
        ),
        per_app_features=per_app,
        scoring_status="models_loaded" if len(models) == 2 else "heuristic_only",
        scoring_message=_scoring_message(models),
        model_versions={kind: record.version for kind, (_m, record) in models.items()},
    )


def _scoring_message(models: dict) -> str:
    if len(models) == 2:
        return (
            "Heuristic scores (0-10) plus LightGBM model scores trained on "
            "synthetic users. The models reproduce the heuristics; they are "
            "not validated against real users. LSTM/autoencoder and SHAP "
            "(M6-M7) are not implemented yet."
        )
    return (
        "Heuristic scores only (0-10). No trained model found: run "
        "`python -m attention_tracker.models.train_cli` from the repo root "
        "to create the M5 models. LSTM/autoencoder and SHAP (M6-M7) are not "
        "implemented yet."
    )