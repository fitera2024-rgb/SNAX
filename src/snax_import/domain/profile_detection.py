from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from uuid import UUID

from snax_import.domain.errors import InvalidValue
from snax_import.domain.supplier_profile import SupplierProfile


class DetectionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DetectionStatus(StrEnum):
    MATCHED = "MATCHED"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    AMBIGUOUS_PROFILE = "AMBIGUOUS_PROFILE"
    TEMPLATE_CHANGED = "TEMPLATE_CHANGED"


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
class ProfileFingerprint:
    """Normalized profile signals used for candidate comparison."""

    filename_pattern: str | None
    extensions: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    sheet_names: tuple[str, ...] = ()
    column_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.filename_pattern is not None and not self.filename_pattern.strip():
            raise InvalidValue("fingerprint.filenamePattern", "Шаблон имени не может быть пустым")
        for field_name in ("extensions", "media_types", "sheet_names", "column_names"):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise InvalidValue(f"fingerprint.{field_name}", "Значения должны быть строками")
            object.__setattr__(self, field_name, values)

    def to_dict(self) -> dict[str, object]:
        return {
            "filenamePattern": self.filename_pattern,
            "extensions": list(self.extensions),
            "mediaTypes": list(self.media_types),
            "sheetNames": list(self.sheet_names),
            "columnNames": list(self.column_names),
        }


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    score: float
    weight: float

    def __post_init__(self) -> None:
        for field_name in ("score", "weight"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                raise InvalidValue(field_name, "Компонент score должен быть в диапазоне 0..100")
        if self.score > self.weight:
            raise InvalidValue("score", "Score компонента не может превышать его вес")

    def to_dict(self) -> dict[str, float]:
        return {"score": self.score, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class ProfileMatchCandidate:
    profile_id: UUID
    version: int
    total_score: float
    confidence: DetectionConfidence
    fingerprint: ProfileFingerprint
    reasons: tuple[str, ...] = ()
    score_components: Mapping[str, ScoreComponent] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, UUID):
            raise InvalidValue("profileId", "Profile id должен быть UUID")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvalidValue("version", "Версия профиля должна быть положительным целым числом")
        if (
            isinstance(self.total_score, bool)
            or not isinstance(self.total_score, (int, float))
            or not math.isfinite(float(self.total_score))
            or not 0.0 <= float(self.total_score) <= 100.0
        ):
            raise InvalidValue("totalScore", "Total score должен находиться в диапазоне 0..100")
        if not isinstance(self.confidence, DetectionConfidence):
            raise InvalidValue("confidence", "Confidence должен быть DetectionConfidence")
        if not isinstance(self.fingerprint, ProfileFingerprint):
            raise InvalidValue("fingerprint", "Fingerprint должен быть ProfileFingerprint")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
            raise InvalidValue("reasons", "Причины должны быть непустыми строками")
        object.__setattr__(self, "reasons", reasons)
        components = dict(self.score_components)
        if any(
            not isinstance(name, str) or not name or not isinstance(component, ScoreComponent)
            for name, component in components.items()
        ):
            raise InvalidValue("scoreComponents", "Score components имеют неверный формат")
        if abs(sum(component.score for component in components.values()) - self.total_score) > 0.02:
            raise InvalidValue("totalScore", "Total score должен равняться сумме компонентов")
        object.__setattr__(self, "score_components", MappingProxyType(components))

    @property
    def score(self) -> float:
        """Compatibility ratio used by the selection thresholds."""

        return self.total_score / 100.0

    def to_dict(self) -> dict[str, object]:
        return {
            "profileId": str(self.profile_id),
            "version": self.version,
            "totalScore": self.total_score,
            "confidence": self.confidence.value,
            "fingerprint": self.fingerprint.to_dict(),
            "reasons": list(self.reasons),
            "scoreComponents": {
                name: component.to_dict() for name, component in self.score_components.items()
            },
        }


@dataclass(frozen=True, slots=True)
class DetectionResult:
    selected_profile: SupplierProfile | None
    status: DetectionStatus = DetectionStatus.PROFILE_NOT_FOUND
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
        if not isinstance(self.status, DetectionStatus):
            raise InvalidValue("status", "Status должен быть DetectionStatus")
        if self.selected_profile is not None and self.status is not DetectionStatus.MATCHED:
            raise InvalidValue("status", "Выбранный профиль допустим только для MATCHED")
        if self.selected_profile is None and self.status is DetectionStatus.MATCHED:
            raise InvalidValue("status", "MATCHED требует выбранный профиль")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "issues", issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "selectedProfile": self.selected_profile.to_dict()
            if self.selected_profile is not None
            else None,
            "status": self.status.value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "confidence": self.confidence.value,
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = [
    "DetectionConfidence",
    "DetectionIssue",
    "DetectionResult",
    "DetectionStatus",
    "ProfileFingerprint",
    "ProfileMatchCandidate",
    "ScoreComponent",
    "confidence_for_score",
]
