from pydantic import BaseModel, Field

from attention_tracker.schema.raw_event import RawEvent

MAX_EVENTS_PER_BATCH = 5000


class EventBatch(BaseModel):
    events: list[RawEvent] = Field(..., max_length=MAX_EVENTS_PER_BATCH)

    model_config = {"extra": "forbid"}


class IngestResult(BaseModel):
    accepted: int
    duplicates: int


class ConsentResult(BaseModel):
    user_id: str
    consent_at: str


class SasSvRequest(BaseModel):
    # Only the 10-60 total is accepted: no item wording, no per-item answers.
    sas_sv_total: int = Field(..., ge=10, le=60)

    model_config = {"extra": "forbid"}


class SasSvResult(BaseModel):
    user_id: str
    sas_sv_total: int
    collected_at: str


class DailyScore(BaseModel):
    day: str
    total_time_sec: float
    heuristic_score: float
    distraction_score: float
    addiction_model_score: float | None
    distraction_model_score: float | None
    is_complete: bool
    max_gap_hours: float
    completeness_reason: str


class AppScore(BaseModel):
    day: str
    package_name: str
    category: str
    total_time_sec: float
    session_count: int
    heuristic_score: float
    distraction_score: float
    addiction_model_score: float | None
    distraction_model_score: float | None
    addiction_model_version: str | None
    distraction_model_version: str | None


class ScoresResponse(BaseModel):
    user_id: str
    scoring_status: str
    scoring_message: str
    model_versions: dict[str, str]
    daily: list[DailyScore]
    apps: list[AppScore]


class ModelInfo(BaseModel):
    kind: str
    version: str
    created_at: str | None
    target: str | None
    test_r_squared: float | None
    caveat: str | None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    status: str
    schema_version: int
