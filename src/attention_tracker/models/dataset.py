from dataclasses import dataclass, field

from attention_tracker.pipeline.features.feature_vector import FeatureVector
from attention_tracker.schema.app_metadata import AppCategory

_CATEGORY_ORDER: tuple[AppCategory, ...] = (
    AppCategory.PRODUCTIVE,
    AppCategory.ADDICTIVE,
    AppCategory.ENTERTAINMENT,
    AppCategory.COMMUNICATION,
    AppCategory.UTILITY,
    AppCategory.UNKNOWN,
)

COLUMN_NAMES: tuple[str, ...] = (
    "total_time_sec",
    "session_count",
    "avg_session_duration_sec",
    "max_session_duration_sec",
    "sessions_under_30s_ratio",
    "interarrival_mean_sec",
    "interarrival_under_2min_ratio",
    "late_night_usage_pct",
    "late_night_usage_time_ratio",
    "hourly_usage_entropy",
    "weekend_usage_ratio",
    "productive_interruption_rate",
    *(f"category_{c.value}" for c in _CATEGORY_ORDER),
)


def feature_row(fv: FeatureVector, category: AppCategory) -> list[float]:
    """Encode one FeatureVector + its app's category as a fixed-width
    row matching `COLUMN_NAMES`. Undefined optional features become
    NaN, never 0 — see module docstring."""

    def _or_nan(value: float | None) -> float:
        return float("nan") if value is None else float(value)

    row = [
        float(fv.total_time_sec),
        float(fv.session_count),
        float(fv.avg_session_duration_sec),
        float(fv.max_session_duration_sec),
        float(fv.sessions_under_30s_ratio),
        _or_nan(fv.interarrival_mean_sec),
        _or_nan(fv.interarrival_under_2min_ratio),
        float(fv.late_night_usage_pct),
        float(fv.late_night_usage_time_ratio),
        float(fv.hourly_usage_entropy),
        float(fv.weekend_usage_ratio),
        float(fv.productive_interruption_rate),
    ]
    row.extend(1.0 if category == c else 0.0 for c in _CATEGORY_ORDER)
    return row


@dataclass(frozen=True)
class Dataset:

    rows: list[list[float]]
    targets: list[float]
    groups: list[str]
    column_names: tuple[str, ...] = field(default=COLUMN_NAMES)

    def __post_init__(self) -> None:
        n = len(self.rows)
        if len(self.targets) != n or len(self.groups) != n:
            raise ValueError(
                "rows, targets, and groups must have the same length "
                f"(got {n}, {len(self.targets)}, {len(self.groups)})"
            )
        for i, row in enumerate(self.rows):
            if len(row) != len(self.column_names):
                raise ValueError(
                    f"row {i} has {len(row)} columns, expected "
                    f"{len(self.column_names)} ({self.column_names})"
                )

    def __len__(self) -> int:
        return len(self.rows)