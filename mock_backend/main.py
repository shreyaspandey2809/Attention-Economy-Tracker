from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.completeness import assess_day_completeness
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.synthetic.archetypes import ARCHETYPES
from attention_tracker.synthetic.generator import SyntheticEventGenerator

app = FastAPI(title="Attention Economy Tracker — MOCK backend (demo only)")

# Wide open for local demo purposes only — the real M8 service will
# have its own, tighter CORS policy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_generator = SyntheticEventGenerator()
# Loaded once at startup, not per-request — TaxonomyLoader reads and
# parses a YAML file on construction (see taxonomy_loader.py), which
# would be wasteful to repeat for every /simulate-day call.
_taxonomy = TaxonomyLoader()


class SimulateDayRequest(BaseModel):
    archetype: str
    user_id: str = "demo_user"


class AppFeatureSummary(BaseModel):
    package_name: str

    # Volume (M3)
    session_count: int
    total_time_sec: float
    avg_session_duration_sec: float
    max_session_duration_sec: float

    # Compulsiveness (M3)
    interarrival_mean_sec: float | None
    sessions_under_30s_ratio: float
    interarrival_under_2min_ratio: float | None

    # Temporal (M3)
    late_night_usage_pct: float
    hourly_usage_entropy: float
    weekend_usage_ratio: float

    # Transitions (M3)
    productive_interruption_rate: float

    # Heuristic score (M4 — newly added)
    heuristic_score: float


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
    completeness: CompletenessSummary
    per_app_features: list[AppFeatureSummary]
    scoring_status: str
    scoring_message: str


@app.get("/archetypes")
def list_archetypes() -> list[str]:
    """Lets the frontend populate its dropdown from the real
    registered archetypes instead of a hardcoded copy that could
    drift out of sync with archetypes.py."""
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

    # Real generator, real profile — one simulated day.
    events = _generator.generate(req.user_id, profile, day_start, num_days=1)

    # Real data-quality pipeline: dedup -> session building -> outlier capping.
    quality_result = run_data_quality_pipeline(events)

    # Completeness heuristic (placeholder until M9's real sync
    # heartbeat exists — see quality/completeness.py's docstring).
    # Assessed across ALL of the user's sessions for the day, not
    # per-app, per that module's documented precondition.
    completeness_result = assess_day_completeness(quality_result.sessions)

    # Real windowing + the full M1-M3 FeatureVector (volume,
    # compulsiveness, temporal, transitions) per app, plus the M4
    # heuristic score built on top of each FeatureVector.
    windows = group_sessions_by_user_app_day(quality_result.sessions)
    per_app: list[AppFeatureSummary] = []
    for (user_id, package_name, day), sessions in windows.items():
        fv = build_feature_vector(sessions, _taxonomy)
        app_category = _taxonomy.lookup(fv.package_name).category
        score = compute_heuristic_score(fv, app_category)
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
                hourly_usage_entropy=fv.hourly_usage_entropy,
                weekend_usage_ratio=fv.weekend_usage_ratio,
                productive_interruption_rate=fv.productive_interruption_rate,
                heuristic_score=score,
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
        completeness=CompletenessSummary(
            is_complete=completeness_result.is_complete,
            max_gap_hours=completeness_result.max_gap_hours,
            reason=completeness_result.reason,
        ),
        per_app_features=per_app,
        scoring_status="in_progress",
        scoring_message=(
            "M4 heuristic baseline scores are shown below. LightGBM, "
            "LSTM/autoencoder, and SHAP explainability (M5-M7) are "
            "still under development."
        ),
    )