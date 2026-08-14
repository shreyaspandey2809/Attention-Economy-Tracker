from collections import defaultdict, deque
from dataclasses import dataclass, field

from attention_tracker.schema.raw_event import RawEvent, TERMINAL_EVENT_TYPES
from attention_tracker.schema.session import Session


@dataclass
class SessionBuildResult:
    sessions: list[Session]
    unmatched_opens: list[RawEvent] = field(default_factory=list)
    unmatched_closes: list[RawEvent] = field(default_factory=list)


class SessionBuilder:
    def build(self, events: list[RawEvent]) -> SessionBuildResult:
        events_sorted = sorted(events, key=lambda e: e.timestamp)

        # FIFO queues of pending OPENED events, keyed by (user_id, package_name).
        pending_opens: dict[tuple[str, str], deque[RawEvent]] = defaultdict(deque)
        sessions_by_user: dict[str, list[Session]] = defaultdict(list)
        unmatched_closes: list[RawEvent] = []

        for event in events_sorted:
            key = (event.user_id, event.package_name)
            if event.event_type not in TERMINAL_EVENT_TYPES:
                pending_opens[key].append(event)
                continue

            queue = pending_opens[key]
            if not queue:
                unmatched_closes.append(event)
                continue

            open_event = queue.popleft()
            session = Session(
                user_id=event.user_id,
                package_name=event.package_name,
                session_id=event.session_id,
                start_time=open_event.timestamp,
                end_time=event.timestamp,
                duration_sec=event.session_duration_sec,
            )
            sessions_by_user[event.user_id].append(session)

        unmatched_opens = [e for queue in pending_opens.values() for e in queue]

        all_sessions: list[Session] = []
        for sessions in sessions_by_user.values():
            sessions.sort(key=lambda s: s.start_time)
            for i, session in enumerate(sessions):
                transition_from = sessions[i - 1].package_name if i > 0 else None
                transition_to = (
                    sessions[i + 1].package_name if i < len(sessions) - 1 else None
                )
                sessions[i] = session.model_copy(
                    update={
                        "transition_from": transition_from,
                        "transition_to": transition_to,
                    }
                )
            all_sessions.extend(sessions)

        all_sessions.sort(key=lambda s: s.start_time)

        return SessionBuildResult(
            sessions=all_sessions,
            unmatched_opens=unmatched_opens,
            unmatched_closes=unmatched_closes,
        )