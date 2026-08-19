from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from snax_import.domain.errors import InvalidValue
from snax_import.domain.supplier_profile import SupplierProfile


class DetectionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@runtime_checkable
class DetectionIssue(Protocol):
    """Small serialization contract implemented by ReaderIssue."""

    def to_dict(self) -> dict[str, object]: ...


def confidence_for_score(
    score: float,
    *,
    high_threshold: float = 0.80,
    medium_threshold: float = 0.50,
) -> DetectionConfidence:
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(float(score))
        or not 0.0 <= float(score) <= 1.0
    ):
        raise InvalidValue("score", "Score должен находиться в диапазоне от 0 до 1")
    if not 0.0 <= medium_threshold <= high_threshold <= 1.0:
        raise InvalidValue("confidenceThresholds", "Пороги confidence должны быть упорядочены")
    if score >= high_threshold:
        return DetectionConfidence.HIGH
    if score >= medium_threshold:
        return DetectionConfidence.MEDIUM
    return DetectionConfidence.LOW


@dataclass(frozen=True, slots=True)
class ProfileMatchCandidate:
    profile_id: UUID
    version: int
    score: float
    confidence: DetectionConfidence
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, UUID):
            raise InvalidValue("profileId", "Profile id должен быть UUID")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvalidValue("version", "Версия профиля должна быть положительным целым числом")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(float(self.score))
            or not 0.0 <= float(self.score) <= 1.0
        ):
            raise InvalidValue("score", "Score должен находиться в диапазоне от 0 до 1")
        if not isinstance(self.confidence, DetectionConfidence):
            raise InvalidValue("confidence", "Confidence должен быть DetectionConfidence")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
            raise InvalidValue("reasons", "Причины должны быть непустыми строками")
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "profileId": str(self.profile_id),
            "version": self.version,
            "score": self.score,
            "confidence": self.confidence.value,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class DetectionResult:
    selected_profile: SupplierProfile | None
    candidates: tuple[ProfileMatchCandidate, ...] = ()
    confidence: DetectionConfidence = DetectionConfidence.LOW
    issues: tuple[DetectionIssue, ...] = ()

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        issues = tuple(self.issues)
        if self.selected_profile is not None and not isinstance(
            self.selected_profile, SupplierProfile
        ):
            raise InvalidValue("selectedProfile", "Selected profile должен быть SupplierProfile")
        if any(not isinstance(candidate, ProfileMatchCandidate) for candidate in candidates):
            raise InvalidValue("candidates", "Candidates должны быть ProfileMatchCandidate")
        if any(not isinstance(issue, DetectionIssue) for issue in issues):
            raise InvalidValue("issues", "Issues должны поддерживать DetectionIssue")
        if not isinstance(self.confidence, DetectionConfidence):
            raise InvalidValue("confidence", "Confidence должен быть DetectionConfidence")
        if self.selected_profile is None and self.confidence is DetectionConfidence.HIGH:
            raise InvalidValue(
                "confidence",
                "Без выбранного профиля confidence не может быть HIGH",
            )
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "issues", issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "selectedProfile": self.selected_profile.to_dict()
            if self.selected_profile is not None
            else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "confidence": self.confidence.value,
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = [
    "DetectionConfidence",
    "DetectionIssue",
    "DetectionResult",
    "ProfileMatchCandidate",
    "confidence_for_score",
]
