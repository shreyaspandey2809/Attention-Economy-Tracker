from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class Session(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    package_name: str = Field(..., min_length=1, max_length=255)
    session_id: str = Field(..., min_length=1, max_length=64)

    start_time: datetime
    end_time: datetime
    duration_sec: float = Field(..., ge=0)
    tz_offset_minutes: int = Field(default=0, ge=-720, le=840)

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
        if abs(computed - self.duration_sec) > 1.0:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) is inconsistent with "
                f"end_time - start_time ({computed})"
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def local_start_time(self) -> datetime:
        return (self.start_time + timedelta(minutes=self.tz_offset_minutes)).replace(
            tzinfo=None
        )