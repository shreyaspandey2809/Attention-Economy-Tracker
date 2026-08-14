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

    def _sample_session_count(
        self, profile: ArchetypeProfile, is_weekend: bool = False
    ) -> int:
        mean = profile.sessions_per_day_mean
        if is_weekend:
            mean *= profile.weekend_session_multiplier
        raw = self.rng.lognormvariate(
            _mean_to_mu(mean, profile.sessions_per_day_sigma),
            profile.sessions_per_day_sigma,
        )
        return max(1, round(raw))

    def _sample_duration_sec(
        self, profile: ArchetypeProfile, is_weekend: bool = False
    ) -> float:
        mean = profile.session_duration_mean_sec
        if is_weekend:
            mean *= profile.weekend_duration_multiplier
        raw = self.rng.lognormvariate(
            _mean_to_mu(mean, profile.session_duration_sigma),
            profile.session_duration_sigma,
        )
        # Floor at 1 second — a zero or negative duration isn't
        # physically meaningful and would fail RawEvent validation.
        return max(1.0, raw)

    def _sample_start_time(
        self, day_start: datetime, profile: ArchetypeProfile
    ) -> datetime:
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
        initial_cursor: datetime | None = None,
    ) -> list[RawEvent]:
        if day_start.tzinfo is None:
            raise ValueError("day_start must be timezone-aware")

        events: list[RawEvent] = []
        # weekday(): Monday=0 ... Sunday=6. Saturday/Sunday = weekend.
        is_weekend = day_start.weekday() >= 5
        session_count = self._sample_session_count(profile, is_weekend=is_weekend)

        previous_category: AppCategory | None = None
        previous_package: str | None = None

        # Generate and sort start times so sessions occur in
        # chronological order across the simulated day. These are
        # provisional — the non-overlap pass below may push some of
        # them later.
        raw_starts = sorted(
            self._sample_start_time(day_start, profile) for _ in range(session_count)
        )

        cursor: datetime | None = initial_cursor

        for provisional_start in raw_starts:
            start_time = provisional_start.astimezone(timezone.utc)
            if cursor is not None and start_time < cursor:
                start_time = cursor + timedelta(seconds=1)

            if (
                previous_category is not None
                and self.rng.random() < profile.same_category_continuation_prob
            ):
                category = previous_category
            else:
                category = self._pick_category(profile)

            package_name = self._pick_package(category)
            duration = self._sample_duration_sec(profile, is_weekend=is_weekend)
            end_time = start_time + timedelta(seconds=duration)
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
            cursor = end_time

        return events

    def generate(
        self,
        user_id: str,
        profile: ArchetypeProfile,
        start_date: datetime,
        num_days: int,
        tz_offset_minutes: int = 0,
    ) -> list[RawEvent]:
        all_events: list[RawEvent] = []
        cursor: datetime | None = None
        for day_index in range(num_days):
            day_start = start_date + timedelta(days=day_index)
            day_events = self.generate_day(
                user_id, profile, day_start, tz_offset_minutes, initial_cursor=cursor
            )
            all_events.extend(day_events)
            if day_events:
                cursor = day_events[-1].timestamp
        return sorted(all_events, key=lambda e: e.timestamp)

    def generate_population(
        self,
        population: dict[str, ArchetypeProfile],
        start_date: datetime,
        num_days: int,
        tz_offset_minutes: int = 0,
    ) -> dict[str, list[RawEvent]]:
        return {
            user_id: self.generate(
                user_id, profile, start_date, num_days, tz_offset_minutes
            )
            for user_id, profile in population.items()
        }


def flatten_population(
    population_events: dict[str, list[RawEvent]],
) -> list[RawEvent]:
    """Merge a generate_population() result into one chronologically
    sorted list, as if all users' devices were streaming into the
    same ingestion endpoint."""
    all_events = [e for events in population_events.values() for e in events]
    return sorted(all_events, key=lambda e: e.timestamp)


def build_population_spec(
    archetype_counts: list[tuple[ArchetypeProfile, int]],
    user_id_prefix: str = "user",
) -> dict[str, ArchetypeProfile]:
    population: dict[str, ArchetypeProfile] = {}
    for profile, count in archetype_counts:
        for i in range(count):
            user_id = f"{user_id_prefix}_{profile.name}_{i:03d}"
            population[user_id] = profile
    return population


def _mean_to_mu(mean: float, sigma: float) -> float:
    import math

    return math.log(mean) - (sigma**2) / 2