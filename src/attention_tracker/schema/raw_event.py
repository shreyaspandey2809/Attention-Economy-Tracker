"""
RawEvent — the single point of entry for all usage-lifecycle data,
whether produced by the synthetic generator (M2) or the Android
UsageStatsManager collector (M9).

Design decisions (see synopsis Ch. 6.3.1):
- Timestamps are enforced timezone-aware (UTC) at the boundary to avoid
  downstream local-time bugs. Local time is reconstructed later using
  tz_offset_minutes, never inferred from naive datetimes.
- session_duration_sec and session_id are required on terminal events
  (CLOSED / BACKGROUND) and forbidden on opening events (OPENED /
  FOREGROUND). This is enforced by a model validator, not left as an
  implicit convention that downstream code has to remember.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class EventType(str, Enum):
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    FOREGROUND = "FOREGROUND"
    BACKGROUND = "BACKGROUND"


# Event types that mark the *end* of a session and therefore carry
# session_duration_sec / session_id.
TERMINAL_EVENT_TYPES = {EventType.CLOSED, EventType.BACKGROUND}


class RawEvent(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    package_name: str = Field(..., min_length=1, max_length=255)
    event_type: EventType

    timestamp: datetime
    tz_offset_minutes: int = Field(..., ge=-720, le=840)

    session_duration_sec: float | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, min_length=1, max_length=64)

    model_config = {"extra": "forbid"}

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "timestamp must be timezone-aware; naive datetimes are rejected "
                "at the schema boundary (see synopsis Ch. 6.3.1)"
            )
        # Normalize to UTC so every downstream consumer can assume UTC.
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def terminal_fields_match_event_type(self) -> "RawEvent":
        is_terminal = self.event_type in TERMINAL_EVENT_TYPES

        if is_terminal and self.session_duration_sec is None:
            raise ValueError(
                f"{self.event_type} is a terminal event and requires "
                "session_duration_sec"
            )
        if is_terminal and self.session_id is None:
            raise ValueError(
                f"{self.event_type} is a terminal event and requires session_id"
            )
        if not is_terminal and self.session_duration_sec is not None:
            raise ValueError(
                f"{self.event_type} is an opening event and must not carry "
                "session_duration_sec"
            )
        if not is_terminal and self.session_id is not None:
            raise ValueError(
                f"{self.event_type} is an opening event and must not carry "
                "session_id"
            )
        return self
