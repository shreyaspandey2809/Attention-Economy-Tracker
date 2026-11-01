"""M8 FastAPI service: persistent ingest + scoring on top of SQLite.

Run:  uvicorn attention_tracker.api.app:create_app --factory --port 8001
Env:  ATTENTION_DB_PATH (default ./attention.db), ATTENTION_MODEL_DIR (model registry)
"""

import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response

from attention_tracker.api.auth import Device, make_current_device
from attention_tracker.api.schemas import (
    AppScore,
    ConsentResult,
    DailyScore,
    EventBatch,
    HealthResponse,
    IngestResult,
    ModelInfo,
    ModelsResponse,
    SasSvRequest,
    SasSvResult,
    ScoresResponse,
)
from attention_tracker.api.scoring_job import MODEL_KINDS, ModelCache, ScoringJob
from attention_tracker.models.registry import latest_record
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.storage.db import Database, latest_schema_version
from attention_tracker.storage.repository import Repository

DB_ENV_VAR = "ATTENTION_DB_PATH"
DEFAULT_DB_PATH = "attention.db"


def create_app(
    db_path: str | Path | None = None,
    model_dir: str | Path | None = None,
    taxonomy: TaxonomyLoader | None = None,
) -> FastAPI:
    db = Database(db_path or os.environ.get(DB_ENV_VAR, DEFAULT_DB_PATH))
    repo = Repository(db)
    taxonomy = taxonomy or TaxonomyLoader(include_extended=True)
    repo.seed_app_metadata(taxonomy.entries())
    job = ScoringJob(repo, taxonomy, ModelCache(model_dir))
    current_device = make_current_device(repo)

    app = FastAPI(title="Attention Economy Tracker API (M8)")
    app.state.db, app.state.repo, app.state.job = db, repo, job

    def own_user(user_id: str, device: Device) -> None:
        if device.user_id != user_id:
            raise HTTPException(status_code=403, detail="token does not belong to this user")

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", schema_version=latest_schema_version())

    @app.post("/v1/consent", response_model=ConsentResult)
    def record_consent(device: Device = Depends(current_device)) -> ConsentResult:
        consent_at = repo.set_consent(device.user_id)
        return ConsentResult(user_id=device.user_id, consent_at=consent_at)  # type: ignore[arg-type]

    @app.post("/v1/events", response_model=IngestResult)
    def ingest_events(batch: EventBatch, device: Device = Depends(current_device)) -> IngestResult:
        user = repo.get_user(device.user_id)
        if user is None or user["consent_at"] is None:
            raise HTTPException(status_code=403, detail="consent not recorded; POST /v1/consent first")
        if any(e.user_id != device.user_id for e in batch.events):
            raise HTTPException(status_code=403, detail="event user_id does not match the token's user")
        accepted, duplicates = repo.insert_events(device.user_id, batch.events)
        return IngestResult(accepted=accepted, duplicates=duplicates)

    @app.get("/v1/users/{user_id}/scores", response_model=ScoresResponse)
    def get_scores(
        user_id: str,
        start: date | None = Query(default=None, alias="from"),
        end: date | None = Query(default=None, alias="to"),
        device: Device = Depends(current_device),
    ) -> ScoresResponse:
        own_user(user_id, device)
        job.ensure_scored(user_id)
        versions = job.models.versions()
        both = len(versions) == len(MODEL_KINDS)
        return ScoresResponse(
            user_id=user_id,
            scoring_status="models_loaded" if both else "heuristic_only",
            scoring_message=(
                "Heuristic scores (0-10) plus LightGBM scores trained on synthetic users. "
                "The models reproduce the heuristics; neither is validated against real users yet."
                if both
                else "Heuristic scores only (0-10); no trained model in the registry. "
                "Heuristics are expert-chosen and not validated against real users yet."
            ),
            model_versions=versions,
            daily=[DailyScore(**d) for d in repo.list_daily_scores(user_id, start, end)],
            apps=[
                AppScore(**{k: r[k] for k in AppScore.model_fields})
                for r in repo.list_window_scores(user_id, start, end)
            ],
        )

    @app.post("/v1/labels/sas-sv", response_model=SasSvResult)
    def post_sas_sv(body: SasSvRequest, device: Device = Depends(current_device)) -> SasSvResult:
        collected_at = repo.upsert_sas_sv_total(device.user_id, body.sas_sv_total)
        return SasSvResult(user_id=device.user_id, sas_sv_total=body.sas_sv_total, collected_at=collected_at)

    @app.get("/v1/models", response_model=ModelsResponse)
    def list_models(device: Device = Depends(current_device)) -> ModelsResponse:
        out = []
        for kind in MODEL_KINDS:
            record = latest_record(kind, job.models.model_dir)  # type: ignore[arg-type]
            if record is None:
                continue
            m = record.meta
            out.append(
                ModelInfo(
                    kind=kind,
                    version=record.version,
                    created_at=m.get("created_at"),
                    target=m.get("target"),
                    test_r_squared=m.get("test_r_squared"),
                    caveat=m.get("caveat"),
                )
            )
        return ModelsResponse(models=out)

    @app.get("/v1/users/{user_id}/export")
    def export_user(user_id: str, device: Device = Depends(current_device)) -> dict:
        own_user(user_id, device)
        dump = repo.export_user(user_id)
        if dump is None:
            raise HTTPException(status_code=404, detail="no such user")
        return dump

    @app.delete("/v1/users/{user_id}", status_code=204)
    def delete_user(user_id: str, device: Device = Depends(current_device)) -> Response:
        own_user(user_id, device)
        if not repo.delete_user(user_id):
            raise HTTPException(status_code=404, detail="no such user")
        return Response(status_code=204)

    return app
