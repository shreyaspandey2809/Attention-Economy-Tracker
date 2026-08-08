"""
Archetypes — parameterized behavioral profiles that drive the
synthetic event generator (M2).

Each archetype is a bundle of probability distributions and
preferences, not raw event data itself. The generator (generator.py)
consumes an ArchetypeProfile and produces a valid RawEvent stream.
Keeping the profile declarative like this means Week 4's Binge
Weekend / Deep Worker archetypes are just new profile instances, not
new generation logic.

Two archetypes this week (per the Month-1 plan):
- BALANCED: moderate, evenly distributed usage across categories,
  few late-night sessions, low compulsiveness.
- DOOMSCROLLER: heavy skew toward ADDICTIVE apps, long sessions,
  frequent late-night usage, low switching (stays locked into one
  app for a long time rather than bouncing around).

These are deliberately at opposite ends of the compulsiveness/
addiction spectrum so that downstream model evaluation (M5) has a
clean, unambiguous ordering to validate against: a correctly trained
model must score Doomscroller sessions higher than Balanced ones.
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


ARCHETYPES: dict[str, ArchetypeProfile] = {
    profile.name: profile for profile in (BALANCED, DOOMSCROLLER)
}