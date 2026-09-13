from dataclasses import dataclass

@dataclass(frozen=True)
class HeuristicWeights:
    total_time_sec: float = 0.10
    session_count: float = 0.10
    sessions_under_30s_ratio: float = 0.20
    interarrival_under_2min_ratio: float = 0.20
    late_night_usage_pct: float = 0.15
    weekend_usage_ratio: float = 0.10
    hourly_usage_entropy: float = 0.05
    productive_interruption_rate: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.total_time_sec
            + self.session_count
            + self.sessions_under_30s_ratio
            + self.interarrival_under_2min_ratio
            + self.late_night_usage_pct
            + self.weekend_usage_ratio
            + self.hourly_usage_entropy
            + self.productive_interruption_rate
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"HeuristicWeights must sum to 1.0, got {total}"
            )


@dataclass(frozen=True)
class NormalizationBounds:
    total_time_sec_cap: float = 7200.0  # 2 hours
    session_count_cap: float = 60.0  # COMPULSIVE_CHECKER's designed mean
    productive_app_dampener: float = 0.3


DEFAULT_WEIGHTS = HeuristicWeights()
DEFAULT_BOUNDS = NormalizationBounds()