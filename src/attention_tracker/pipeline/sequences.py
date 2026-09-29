import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

# Order matters: this is the column order of every step vector.
CATEGORY_ORDER: tuple[AppCategory, ...] = (
    AppCategory.ADDICTIVE,
    AppCategory.ENTERTAINMENT,
    AppCategory.COMMUNICATION,
    AppCategory.PRODUCTIVE,
    AppCategory.UTILITY,
    AppCategory.UNKNOWN,
)

STEP_FEATURE_NAMES: tuple[str, ...] = (
    "log1p_duration_sec",
    "log1p_gap_since_prev_sec",
    "hour_sin",
    "hour_cos",
    "is_weekend",
    "is_app_switch",
    *(f"cat_{c.value.lower()}" for c in CATEGORY_ORDER),
)
STEP_DIM = len(STEP_FEATURE_NAMES)

# Gaps longer than this are clipped: the difference between a 9-hour
# and a 12-hour overnight gap is not behavior the model should chase.
MAX_GAP_SEC = 6 * 3600.0
DEFAULT_MAX_LEN = 128


@dataclass(frozen=True)
class SessionSequence:
    user_id: str
    day: date
    steps: list[list[float]]  # max_len x STEP_DIM, zero-padded at the end
    mask: list[int]  # 1 = real step, 0 = padding
    length: int  # real steps kept
    truncated_steps: int  # real steps dropped from the front


def _step_vector(
    session: Session,
    prev: Session | None,
    taxonomy: TaxonomyLoader,
) -> list[float]:
    if prev is None:
        gap = MAX_GAP_SEC  # first session of the day: treated as a long gap
    else:
        gap = (session.start_time - prev.end_time).total_seconds()
        gap = max(0.0, min(gap, MAX_GAP_SEC))

    local = session.local_start_time
    fractional_hour = local.hour + local.minute / 60.0
    angle = 2 * math.pi * fractional_hour / 24.0

    is_switch = 1.0 if prev is not None and prev.package_name != session.package_name else 0.0

    category = taxonomy.lookup(session.package_name).category
    one_hot = [1.0 if category == c else 0.0 for c in CATEGORY_ORDER]

    return [
        math.log1p(session.duration_sec),
        math.log1p(gap),
        math.sin(angle),
        math.cos(angle),
        1.0 if local.isoweekday() in (6, 7) else 0.0,
        is_switch,
        *one_hot,
    ]


def build_day_sequences(
    sessions: list[Session],
    taxonomy: TaxonomyLoader,
    max_len: int = DEFAULT_MAX_LEN,
) -> list[SessionSequence]:
    """One SessionSequence per (user, local day), sorted by user then day.

    `sessions` may hold many users and days; they are grouped here.
    The gap for the first session of a day is measured as "no previous
    session today" rather than against the prior day's last session,
    so a day's sequence depends only on that day's data.
    """
    if max_len < 1:
        raise ValueError("max_len must be at least 1")

    groups: dict[tuple[str, date], list[Session]] = defaultdict(list)
    for s in sessions:
        groups[(s.user_id, s.local_start_time.date())].append(s)

    sequences: list[SessionSequence] = []
    for (user_id, day) in sorted(groups):
        day_sessions = sorted(groups[(user_id, day)], key=lambda s: s.start_time)

        vectors: list[list[float]] = []
        prev: Session | None = None
        for s in day_sessions:
            vectors.append(_step_vector(s, prev, taxonomy))
            prev = s

        dropped = max(0, len(vectors) - max_len)
        kept = vectors[dropped:]
        length = len(kept)
        padding = [[0.0] * STEP_DIM for _ in range(max_len - length)]

        sequences.append(
            SessionSequence(
                user_id=user_id,
                day=day,
                steps=kept + padding,
                mask=[1] * length + [0] * (max_len - length),
                length=length,
                truncated_steps=dropped,
            )
        )
    return sequences