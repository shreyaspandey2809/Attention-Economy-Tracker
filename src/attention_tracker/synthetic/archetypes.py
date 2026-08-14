from dataclasses import dataclass, field

from attention_tracker.schema.app_metadata import AppCategory


@dataclass(frozen=True)
class ArchetypeProfile:
    name: str
    category_weights: dict[AppCategory, float]
    session_duration_mean_sec: float
    session_duration_sigma: float
    sessions_per_day_mean: float
    sessions_per_day_sigma: float
    late_night_session_fraction: float
    same_category_continuation_prob: float
    description: str = ""
    weekend_session_multiplier: float = 1.0
    weekend_duration_multiplier: float = 1.0


BALANCED = ArchetypeProfile(
    name="BALANCED",
    category_weights={
        AppCategory.PRODUCTIVE: 0.30,
        AppCategory.COMMUNICATION: 0.25,
        AppCategory.UTILITY: 0.20,
        AppCategory.ENTERTAINMENT: 0.15,
        AppCategory.ADDICTIVE: 0.10,
    },
    session_duration_mean_sec=180.0,   # ~3 min average session
    session_duration_sigma=0.6,
    sessions_per_day_mean=25.0,
    sessions_per_day_sigma=0.4,
    late_night_session_fraction=0.03,
    same_category_continuation_prob=0.35,
    description=(
        "Moderate, evenly-spread usage. Short-to-medium sessions, "
        "rarely late at night, switches categories often rather than "
        "chaining sessions within the same one."
    ),
)

DOOMSCROLLER = ArchetypeProfile(
    name="DOOMSCROLLER",
    category_weights={
        AppCategory.ADDICTIVE: 0.55,
        AppCategory.ENTERTAINMENT: 0.20,
        AppCategory.COMMUNICATION: 0.15,
        AppCategory.UTILITY: 0.07,
        AppCategory.PRODUCTIVE: 0.03,
    },
    session_duration_mean_sec=600.0,   # ~10 min average session
    session_duration_sigma=0.9,
    sessions_per_day_mean=18.0,
    sessions_per_day_sigma=0.5,
    late_night_session_fraction=0.35,
    same_category_continuation_prob=0.75,
    description=(
        "Heavily skewed toward addictive short-form apps. Long "
        "sessions, frequent late-night use, and a strong tendency to "
        "chain sessions within the same (addictive) category rather "
        "than switching out."
    ),
)

BINGE_WEEKEND = ArchetypeProfile(
    name="BINGE_WEEKEND",
    category_weights={
        AppCategory.ENTERTAINMENT: 0.45,
        AppCategory.ADDICTIVE: 0.25,
        AppCategory.COMMUNICATION: 0.15,
        AppCategory.UTILITY: 0.10,
        AppCategory.PRODUCTIVE: 0.05,
    },
    session_duration_mean_sec=240.0,   # weekday baseline, ~4 min
    session_duration_sigma=0.7,
    sessions_per_day_mean=15.0,        # weekday baseline — fairly light
    sessions_per_day_sigma=0.4,
    late_night_session_fraction=0.10,
    same_category_continuation_prob=0.55,
    weekend_session_multiplier=2.8,    # far more sessions Sat/Sun
    weekend_duration_multiplier=2.2,   # and each one runs much longer
    description=(
        "Restrained on weekdays — close to Balanced levels — but "
        "usage surges sharply on Saturday/Sunday: more sessions, "
        "each running much longer, concentrated in Entertainment. "
        "Distinguishes itself from Doomscroller by being genuinely "
        "moderate most of the week rather than uniformly heavy."
    ),
)

DEEP_WORKER = ArchetypeProfile(
    name="DEEP_WORKER",
    category_weights={
        AppCategory.PRODUCTIVE: 0.55,
        AppCategory.COMMUNICATION: 0.25,
        AppCategory.UTILITY: 0.15,
        AppCategory.ENTERTAINMENT: 0.04,
        AppCategory.ADDICTIVE: 0.01,
    },
    session_duration_mean_sec=900.0,   # long, focused sessions (~15 min)
    session_duration_sigma=0.5,        # low variance — consistent, not bursty
    sessions_per_day_mean=8.0,         # few sessions...
    sessions_per_day_sigma=0.3,        # ...and consistently few
    late_night_session_fraction=0.02,
    same_category_continuation_prob=0.70,  # stays in Productive once there
    weekend_session_multiplier=0.6,    # noticeably lighter on weekends
    weekend_duration_multiplier=0.8,
    description=(
        "Low session count but long, focused, low-variance sessions "
        "concentrated in Productive apps. The near-inverse of "
        "Doomscroller: infrequent switching, minimal addictive-app "
        "time, and usage that drops off on weekends rather than "
        "spiking."
    ),
)


ARCHETYPES: dict[str, ArchetypeProfile] = {
    profile.name: profile
    for profile in (BALANCED, DOOMSCROLLER, BINGE_WEEKEND, DEEP_WORKER)
}