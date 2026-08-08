"""
Archetypes — parameterized behavioral profiles that drive the
synthetic event generator (M2).

Each archetype is a bundle of probability distributions and
preferences, not raw event data itself. The generator (generator.py)
consumes an ArchetypeProfile and produces a valid RawEvent stream.

Four archetypes (per the Month-1 plan, Weeks 3-4):
- BALANCED: moderate, evenly distributed usage across categories,
  few late-night sessions, low compulsiveness. (Week 3)
- DOOMSCROLLER: heavy skew toward ADDICTIVE apps, long sessions,
  frequent late-night usage, low switching (stays locked into one
  app for a long time rather than bouncing around). (Week 3)
- BINGE_WEEKEND: restrained weekday usage close to Balanced, but a
  sharp weekday/weekend split — far more and far longer sessions on
  Saturday/Sunday, concentrated in Entertainment. (Week 4)
- DEEP_WORKER: few sessions per day, but long and low-variance,
  almost entirely in Productive apps; usage drops further on
  weekends rather than spiking. (Week 4)

These span the compulsiveness/addiction spectrum with two additional
axes beyond Balanced/Doomscroller: Binge Weekend adds a temporal
(weekday-vs-weekend) dimension, and Deep Worker sits at the opposite
extreme from Doomscroller on category composition. Together they give
M5's model evaluation a richer ordering to validate against than a
single high/low pair would.
"""

from dataclasses import dataclass, field

from attention_tracker.schema.app_metadata import AppCategory


@dataclass(frozen=True)
class ArchetypeProfile:
    name: str

    # Relative likelihood of opening an app from each category.
    # Need not sum to 1.0 — the generator normalizes.
    category_weights: dict[AppCategory, float]

    # Session duration is drawn from a lognormal distribution,
    # parameterized in seconds (mean, sigma control shape/spread).
    session_duration_mean_sec: float
    session_duration_sigma: float

    # Sessions per active day (lognormal mean/sigma, in count of
    # sessions), used by the generator to decide how many events to
    # emit for a given simulated day.
    sessions_per_day_mean: float
    sessions_per_day_sigma: float

    # Fraction of sessions that start between 23:00 and 04:00 local
    # time. Doomscroller should be high here; Balanced should be low.
    late_night_session_fraction: float

    # Probability that, after closing an app, the very next app
    # opened belongs to the SAME category (as opposed to switching
    # categories). High value = "stays in a lane"; low value =
    # frequent category-hopping.
    same_category_continuation_prob: float

    # Optional per-archetype notes, not consumed by the generator —
    # documentation only, so a reader doesn't have to reverse-engineer
    # intent from the numbers alone.
    description: str = ""

    # Multiplier applied to sessions_per_day_mean on Saturday/Sunday.
    # 1.0 (default) means no weekday/weekend difference. Added for
    # BINGE_WEEKEND, whose entire defining trait is a weekday/weekend
    # split that no other field can express — rather than special-
    # casing that one archetype in the generator, every profile gets
    # this knob and most just leave it at the neutral default.
    weekend_session_multiplier: float = 1.0

    # Multiplier applied to session_duration_mean_sec on Saturday/
    # Sunday. Same rationale as above — BINGE_WEEKEND sessions aren't
    # just more frequent on weekends, they run longer too.
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