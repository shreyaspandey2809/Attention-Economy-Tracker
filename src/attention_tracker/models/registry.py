import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from attention_tracker.models.dataset import COLUMN_NAMES
from attention_tracker.models.lightgbm_scorer import ModelKind, TrainedModel, TrainResult

DEFAULT_REGISTRY_DIR = Path("models_artifacts")
REGISTRY_ENV_VAR = "ATTENTION_MODEL_DIR"
META_SCHEMA_VERSION = 1
_KINDS: tuple[str, ...] = ("addiction", "distraction")


def default_registry_dir() -> Path:
    return Path(os.environ.get(REGISTRY_ENV_VAR, DEFAULT_REGISTRY_DIR))


@dataclass(frozen=True)
class ModelRecord:
    kind: str
    version: str
    path: Path
    meta: dict


def _version_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def save_model(
    result: TrainResult,
    root: Path | str | None = None,
    version: str | None = None,
    extra_meta: dict | None = None,
) -> ModelRecord:
    import lightgbm as lgb

    model = result.model
    root_path = Path(root) if root is not None else default_registry_dir()
    version = version or _version_now()
    out_dir = root_path / model.kind / version
    if out_dir.exists():
        raise FileExistsError(f"model version already exists: {out_dir}")
    out_dir.mkdir(parents=True)

    model.booster.save_model(str(out_dir / "model.txt"))
    meta = {
        "schema_version": META_SCHEMA_VERSION,
        "kind": model.kind,
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "columns": list(model.columns),
        "lightgbm_version": lgb.__version__,
        "best_iteration": result.best_iteration,
        "target": "heuristic_distillation_synthetic",
        "val_r_squared": result.val_distillation.r_squared,
        "test_r_squared": result.test_distillation.r_squared,
        "test_n_windows": result.test_distillation.n_windows,
        "caveat": result.test_distillation.caveat,
    }
    if extra_meta:
        meta.update(extra_meta)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return ModelRecord(kind=model.kind, version=version, path=out_dir, meta=meta)


def load_model(model_dir: Path | str) -> TrainedModel:
    """Load a model saved by `save_model`. Raises ValueError when its
    feature schema no longer matches the code (retrain in that case)."""
    import lightgbm as lgb

    model_dir = Path(model_dir)
    meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))
    columns = list(meta["columns"])
    unknown = [c for c in columns if c not in COLUMN_NAMES]
    if unknown:
        raise ValueError(
            f"model at {model_dir} uses columns this code no longer has: {unknown}; retrain it"
        )
    booster = lgb.Booster(model_file=str(model_dir / "model.txt"))
    return TrainedModel(booster=booster, kind=meta["kind"], columns=columns)


def list_versions(kind: ModelKind, root: Path | str | None = None) -> list[ModelRecord]:
    root_path = Path(root) if root is not None else default_registry_dir()
    kind_dir = root_path / kind
    if not kind_dir.is_dir():
        return []
    records = []
    for d in sorted(p for p in kind_dir.iterdir() if (p / "meta.json").is_file()):
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        records.append(ModelRecord(kind=kind, version=d.name, path=d, meta=meta))
    return records


def latest_record(kind: ModelKind, root: Path | str | None = None) -> ModelRecord | None:
    versions = list_versions(kind, root)
    return versions[-1] if versions else None


def load_latest(
    kind: ModelKind, root: Path | str | None = None
) -> tuple[TrainedModel, ModelRecord] | None:
    record = latest_record(kind, root)
    if record is None:
        return None
    return load_model(record.path), record


def known_kinds() -> tuple[str, ...]:
    return _KINDS