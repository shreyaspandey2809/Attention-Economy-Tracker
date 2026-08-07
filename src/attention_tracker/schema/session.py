"""
Session — the joined representation of one OPENED/FOREGROUND paired
with its matching CLOSED/BACKGROUND event. Session Builder (M3, Week
7) constructs these from a RawEvent stream; this week only defines
the shape and its internal-consistency validation, since the feature
pipeline (M3) needs a stable target type to design against before the
builder itself exists.

transition_from / transition_to capture what app (if any) the user
came from and went to — the raw material for M3's transition features
(e.g. productive_interruption_rate).
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator


class Session(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    package_name: str = Field(..., min_length=1, max_length=255)
    session_id: str = Field(..., min_length=1, max_length=64)

    start_time: datetime
    end_time: datetime
    duration_sec: float = Field(..., ge=0)

    transition_from: str | None = Field(default=None, max_length=255)
    transition_to: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}

    @field_validator("start_time", "end_time")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Session timestamps must be timezone-aware")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def end_after_start_and_duration_consistent(self) -> "Session":
        if self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")

        computed = (self.end_time - self.start_time).total_seconds()
        # Allow small float slack (e.g. rounding from the Android
        # collector's own duration measurement vs. our derived one).
        if abs(computed - self.duration_sec) > 1.0:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) is inconsistent with "
                f"end_time - start_time ({computed})"
            )
        return self
