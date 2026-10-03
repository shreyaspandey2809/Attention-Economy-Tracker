from dataclasses import dataclass, field
from datetime import datetime, timezone

from attention_tracker.models.dataset import Dataset, feature_row
from attention_tracker.pipeline.features.feature_vector import build_feature_vector
from attention_tracker.pipeline.quality.pipeline import run_data_quality_pipeline
from attention_tracker.pipeline.windowing import group_sessions_by_user_app_week
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.scoring.heuristic import compute_heuristic_score
from attention_tracker.synthetic.archetypes import ARCHETYPES, ArchetypeProfile
from attention_tracker.synthetic.generator import SyntheticEventGenerator


@dataclass(frozen=True)
class SyntheticDatasetConfig:
    seeds_per_archetype: int = 20
    num_days: int = 28
    start_date_iso: str = "2026-01-05T00:00:00+00:00"  # a Monday
    taxonomy: TaxonomyLoader = field(default_factory=TaxonomyLoader)
    archetypes: tuple[ArchetypeProfile, ...] = field(
        default_factory=lambda: tuple(ARCHETYPES.values())
    )


def build_synthetic_distillation_dataset(
    config: SyntheticDatasetConfig = SyntheticDatasetConfig(),
    seed_offset: int = 0,
) -> Dataset:
    import random

    start_date = datetime.fromisoformat(config.start_date_iso)
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)

    rows: list[list[float]] = []
    targets: list[float] = []
    groups: list[str] = []

    for archetype in config.archetypes:
        for seed in range(seed_offset, seed_offset + config.seeds_per_archetype):
            user_id = f"synth_{archetype.name}_{seed:05d}"
            rng = random.Random(seed * 7919 + hash(archetype.name) % 10_000)
            generator = SyntheticEventGenerator(taxonomy=config.taxonomy, rng=rng)
            events = generator.generate(
                user_id=user_id,
                profile=archetype,
                start_date=start_date,
                num_days=config.num_days,
            )
            if not events:
                continue

            quality_result = run_data_quality_pipeline(events, taxonomy=config.taxonomy)
            windows = group_sessions_by_user_app_week(quality_result.sessions)

            for (_user, package_name, _week_start), sessions in windows.items():
                fv = build_feature_vector(sessions, config.taxonomy)
                category = config.taxonomy.lookup(package_name).category
                score = compute_heuristic_score(fv, category)

                rows.append(feature_row(fv, category))
                targets.append(score)
                groups.append(user_id)

    return Dataset(rows=rows, targets=targets, groups=groups)