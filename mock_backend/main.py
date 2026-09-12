from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from attention_tracker.pipeline.features.compulsiveness import (
    interarrival_mean_sec,
    sessions_under_30s_ratio,
)
from attention_tracker.pipeline.features.volume import (
    avg_session_duration_sec,
    max_session_duration_sec,
    session_count,
    total_time_sec,
)
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_day
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


class SimulateDayResponse(BaseModel):
    archetype: str
    user_id: str
    raw_event_count: int
    duplicate_count: int
    session_count_total: int
    outliers_capped: int
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

    # Real windowing + real M1-M3 feature functions, per app.
    windows = group_sessions_by_user_app_day(quality_result.sessions)
    per_app: list[AppFeatureSummary] = []
    for (user_id, package_name, day), sessions in windows.items():
        per_app.append(
            AppFeatureSummary(
                package_name=package_name,
                session_count=session_count(sessions),
                total_time_sec=total_time_sec(sessions),
                avg_session_duration_sec=avg_session_duration_sec(sessions),
                max_session_duration_sec=max_session_duration_sec(sessions),
                interarrival_mean_sec=(
                    interarrival_mean_sec(sessions) if len(sessions) >= 2 else None
                ),
                sessions_under_30s_ratio=sessions_under_30s_ratio(sessions),
            )
        )
    per_app.sort(key=lambda a: a.total_time_sec, reverse=True)

    return SimulateDayResponse(
        archetype=req.archetype,
        user_id=req.user_id,
        raw_event_count=len(events),
        duplicate_count=quality_result.dedup_result.duplicate_count,
        session_count_total=len(quality_result.sessions),
        outliers_capped=quality_result.outlier_result.capped_count,
        per_app_features=per_app,
        scoring_status="in_progress",
        scoring_message=(
            "Addiction/distraction scoring (M4-M7: heuristic baseline, "
            "LightGBM, LSTM/autoencoder, SHAP explainability) is still "
            "under development. This response shows real computed "
            "behavioral features (M1-M3) only."
        ),
    )