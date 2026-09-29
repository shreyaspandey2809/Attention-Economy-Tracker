from dataclasses import dataclass
from enum import Enum

SAS_SV_NUM_ITEMS = 10
SAS_SV_MIN_ITEM = 1
SAS_SV_MAX_ITEM = 6
SAS_SV_MIN_TOTAL = SAS_SV_NUM_ITEMS * SAS_SV_MIN_ITEM  # 10
SAS_SV_MAX_TOTAL = SAS_SV_NUM_ITEMS * SAS_SV_MAX_ITEM  # 60
SAS_SV_CUTOFF_MALE = 31
SAS_SV_CUTOFF_FEMALE = 33


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNSPECIFIED = "UNSPECIFIED"


class LabelError(ValueError):
    """Raised for a malformed self-report response."""


@dataclass(frozen=True)
class SasSvResponse:
    """One participant's SAS-SV answers, linked to a pseudonymous
    user_id (the same id used in the usage data). No name, phone
    number, or other identifier belongs here."""

    user_id: str
    item_scores: tuple[int, ...]
    sex: Sex = Sex.UNSPECIFIED

    def __post_init__(self) -> None:
        if not self.user_id:
            raise LabelError("user_id must be non-empty")
        if len(self.item_scores) != SAS_SV_NUM_ITEMS:
            raise LabelError(
                f"SAS-SV needs exactly {SAS_SV_NUM_ITEMS} item scores, "
                f"got {len(self.item_scores)}"
            )
        for i, score in enumerate(self.item_scores, start=1):
            if isinstance(score, bool) or not isinstance(score, int):
                raise LabelError(f"item {i} must be an int, got {score!r}")
            if not SAS_SV_MIN_ITEM <= score <= SAS_SV_MAX_ITEM:
                raise LabelError(
                    f"item {i} must be {SAS_SV_MIN_ITEM}-{SAS_SV_MAX_ITEM}, got {score}"
                )

    @property
    def total(self) -> int:
        return sum(self.item_scores)

    @property
    def cutoff(self) -> int | None:
        """Sex-specific published cut-off, or None if sex unspecified."""
        if self.sex == Sex.MALE:
            return SAS_SV_CUTOFF_MALE
        if self.sex == Sex.FEMALE:
            return SAS_SV_CUTOFF_FEMALE
        return None

    @property
    def at_risk(self) -> bool | None:
        """True/False against the published cut-off; None when sex is
        unspecified, because guessing a cut-off would be inventing one."""
        cutoff = self.cutoff
        if cutoff is None:
            return None
        return self.total >= cutoff