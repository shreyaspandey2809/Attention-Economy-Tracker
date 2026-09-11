from dataclasses import dataclass, field
from attention_tracker.schema.raw_event import RawEvent, TERMINAL_EVENT_TYPES


@dataclass
class DedupResult:
    events: list[RawEvent]
    duplicate_count: int = 0
    duplicate_session_ids: list[str] = field(default_factory=list)
    duplicate_open_keys: list[tuple[str, str, str]] = field(default_factory=list)


def dedupe_events(events: list[RawEvent]) -> DedupResult:
    seen_session_ids: set[str] = set()
    seen_open_keys: set[tuple[str, str, str]] = set()

    kept: list[RawEvent] = []
    duplicate_session_ids: list[str] = []
    duplicate_open_keys: list[tuple[str, str, str]] = []

    for event in events:
        if event.event_type in TERMINAL_EVENT_TYPES:
            # session_id is guaranteed non-None on terminal events by
            # RawEvent's model_validator.
            key = event.session_id
            if key in seen_session_ids:
                duplicate_session_ids.append(key)
                continue
            seen_session_ids.add(key)
            kept.append(event)
        else:
            open_key = (
                event.user_id,
                event.package_name,
                event.timestamp.isoformat(),
            )
            if open_key in seen_open_keys:
                duplicate_open_keys.append(open_key)
                continue
            seen_open_keys.add(open_key)
            kept.append(event)

    return DedupResult(
        events=kept,
        duplicate_count=len(duplicate_session_ids) + len(duplicate_open_keys),
        duplicate_session_ids=duplicate_session_ids,
        duplicate_open_keys=duplicate_open_keys,
    )