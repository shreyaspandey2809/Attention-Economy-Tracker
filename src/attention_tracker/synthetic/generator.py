"""
Generator — turns an ArchetypeProfile into a stream of valid RawEvent
pairs (OPENED + matching CLOSED) for one simulated user over one or
more days.

Design notes:
- Every event emitted is passed through RawEvent's own validators
  (by construction — we build RawEvent instances, not raw dicts), so
  a bug here that produces e.g. a naive timestamp fails loudly at
  generation time rather than silently downstream.
- The generator picks apps by first sampling a category from the
  profile's category_weights, then a concrete package_name from the
  taxonomy within that category. same_category_continuation_prob
  controls whether the NEXT session stays in the same category as
  the one just closed.
- Session count and duration are drawn from lognormal distributions
  (mean/sigma from the profile) since real usage-count and duration
  data is right-skewed: most sessions short, a long tail of long
  ones. This is a modeling choice, not a hard requirement — later
  weeks can swap distributions per-archetype if evaluation (M5)
  shows synthetic data doesn't separate archetypes cleanly enough.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.raw_event import EventType, RawEvent
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.synthetic.archetypes import ArchetypeProfile


class SyntheticEventGenerator:
    def __init__(
        self,
        taxonomy: TaxonomyLoader | None = None,
        rng: random.Random | None = None,
    ):
        self.taxonomy = taxonomy or TaxonomyLoader()
        self.rng = rng or random.Random()

        # Precompute category -> [package_name, ...] so sampling a
        # concrete app within a chosen category is O(1) amortized.
        self._by_category: dict[AppCategory, list[str]] = {}
        for pkg, entry in self.taxonomy._entries.items():  # noqa: SLF001
            self._by_category.setdefault(entry.category, []).append(pkg)

    def _pick_category(self, profile: ArchetypeProfile) -> AppCategory:
        categories = list(profile.category_weights.keys())
        weights = list(profile.category_weights.values())
        return self.rng.choices(categories, weights=weights, k=1)[0]

    def _pick_package(self, category: AppCategory) -> str:
        candidates = self._by_category.get(category)
        if not candidates:
            raise ValueError(
                f"taxonomy has no apps in category {category}; cannot "
                "generate a session for this category"
            )
        return self.rng.choice(candidates)

    def _sample_session_count(self, profile: ArchetypeProfile) -> int:
        raw = self.rng.lognormvariate(
            _mean_to_mu(profile.sessions_per_day_mean, profile.sessions_per_day_sigma),
            profile.sessions_per_day_sigma,
        )
        return max(1, round(raw))

    def _sample_duration_sec(self, profile: ArchetypeProfile) -> float:
        raw = self.rng.lognormvariate(
            _mean_to_mu(
                profile.session_duration_mean_sec, profile.session_duration_sigma
            ),
            profile.session_duration_sigma,
        )
        # Floor at 1 second — a zero or negative duration isn't
        # physically meaningful and would fail RawEvent validation.
        return max(1.0, raw)

    def _sample_start_time(
        self, day_start: datetime, profile: ArchetypeProfile
    ) -> datetime:
        """Pick a start time within the 24h window beginning at
        day_start, biased toward late-night hours per the profile's
        late_night_session_fraction."""
        if self.rng.random() < profile.late_night_session_fraction:
            # Late night: 23:00-04:00 the following day.
            hour = self.rng.choice([23, 0, 1, 2, 3])
        else:
            # Waking hours: 06:00-22:00, uniform.
            hour = self.rng.randint(6, 22)
        minute = self.rng.randint(0, 59)
        second = self.rng.randint(0, 59)

        base_day = day_start
        if hour == 23:
            offset_day = base_day
        elif hour <= 4:
            offset_day = base_day + timedelta(days=1) if hour != 0 else base_day
        else:
            offset_day = base_day

        return offset_day.replace(hour=hour, minute=minute, second=second)

    def generate_day(
        self,
        user_id: str,
        profile: ArchetypeProfile,
        day_start: datetime,
        tz_offset_minutes: int = 0,
    ) -> list[RawEvent]:
        """Generate one simulated day of sessions for a single user,
        as a flat list of RawEvent (OPENED immediately followed by
        its matching CLOSED, per session)."""
        if day_start.tzinfo is None:
            raise ValueError("day_start must be timezone-aware")

        events: list[RawEvent] = []
        session_count = self._sample_session_count(profile)

        previous_category: AppCategory | None = None
        previous_package: str | None = None

        # Generate and sort start times so sessions occur in
        # chronological order across the simulated day.
        raw_starts = sorted(
            self._sample_start_time(day_start, profile) for _ in range(session_count)
        )

        for start_time in raw_starts:
            if (
                previous_category is not None
                and self.rng.random() < profile.same_category_continuation_prob
            ):
                category = previous_category
            else:
                category = self._pick_category(profile)

            package_name = self._pick_package(category)
            duration = self._sample_duration_sec(profile)
            end_time = start_time.astimezone(timezone.utc) + timedelta(
                seconds=duration
            )
            session_id = f"syn_{uuid.uuid4().hex[:16]}"

            events.append(
                RawEvent(
                    user_id=user_id,
                    package_name=package_name,
                    event_type=EventType.OPENED,
                    timestamp=start_time,
                    tz_offset_minutes=tz_offset_minutes,
                )
            )
            events.append(
                RawEvent(
                    user_id=user_id,
                    package_name=package_name,
                    event_type=EventType.CLOSED,
                    timestamp=end_time,
                    tz_offset_minutes=tz_offset_minutes,
                    session_duration_sec=duration,
                    session_id=session_id,
                )
            )

            previous_category = category
            previous_package = package_name  # noqa: F841 — reserved for M3 transition wiring

        return events

    def generate(
        self,
        user_id: str,
        profile: ArchetypeProfile,
        start_date: datetime,
        num_days: int,
        tz_offset_minutes: int = 0,
    ) -> list[RawEvent]:
        """Generate `num_days` consecutive simulated days for one
        user under one archetype. Returns a flat, chronologically
        sorted list of RawEvent."""
        all_events: list[RawEvent] = []
        for day_index in range(num_days):
            day_start = start_date + timedelta(days=day_index)
            all_events.extend(
                self.generate_day(user_id, profile, day_start, tz_offset_minutes)
            )
        return sorted(all_events, key=lambda e: e.timestamp)


def _mean_to_mu(mean: float, sigma: float) -> float:
    """Convert a desired lognormal mean into the mu parameter that
    random.lognormvariate expects, given sigma. Standard lognormal
    mean formula: mean = exp(mu + sigma^2 / 2) => mu = ln(mean) - sigma^2/2.
    """
    import math

    return math.log(mean) - (sigma**2) / 2