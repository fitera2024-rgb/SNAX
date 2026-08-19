from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from snax_import.domain.profile_detection import (
    DetectionConfidence,
    DetectionResult,
    DetectionStatus,
    ProfileFingerprint,
    ProfileMatchCandidate,
    ScoreComponent,
    confidence_for_score,
)
from snax_import.domain.raw_workbook import RawWorkbook, Workbook
from snax_import.domain.supplier_profile import (
    SupplierFileRule,
    SupplierProfile,
    SupplierProfileVersion,
)
from snax_import.ports.workbook_reader import (
    IssueSeverity,
    ReaderIssue,
    ReaderIssueCode,
)


def _validate_ratio(value: float, field_name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ProfileDetectionWeights:
    """Configurable feature weights; scores are normalized by active weights."""

    filename: float = 0.20
    sheet: float = 0.30
    columns: float = 0.40
    extension: float = 0.10
    media_type: float = 0.0

    def __post_init__(self) -> None:
        for field_name in (
            "filename",
            "sheet",
            "columns",
            "extension",
            "media_type",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise ValueError(f"{field_name} weight must be a non-negative finite number")
        if (
            sum(
                float(getattr(self, field_name))
                for field_name in (
                    "filename",
                    "sheet",
                    "columns",
                    "extension",
                    "media_type",
                )
            )
            <= 0.0
        ):
            raise ValueError("At least one detection weight must be positive")

    def for_feature(self, feature: str) -> float:
        return float(getattr(self, feature))


@dataclass(frozen=True, slots=True)
class ProfileDetectionConfig:
    weights: ProfileDetectionWeights = field(default_factory=ProfileDetectionWeights)
    selection_threshold: float = 0.50
    ambiguity_margin: float = 0.05
    high_confidence_threshold: float = 0.80
    medium_confidence_threshold: float = 0.50
    structural_compatibility_threshold: float = 0.50

    def __post_init__(self) -> None:
        for field_name in (
            "selection_threshold",
            "ambiguity_margin",
            "high_confidence_threshold",
            "medium_confidence_threshold",
            "structural_compatibility_threshold",
        ):
            _validate_ratio(float(getattr(self, field_name)), field_name)
        if self.medium_confidence_threshold > self.high_confidence_threshold:
            raise ValueError("medium_confidence_threshold cannot exceed high_confidence_threshold")


@dataclass(frozen=True, slots=True)
class _ScoredProfile:
    profile: SupplierProfile
    candidate: ProfileMatchCandidate
    component_ratios: dict[str, float]


class SupplierProfileDetector:
    """Detect an active supplier profile from technical workbook signals only."""

    _FEATURES = ("filename", "sheet", "columns", "extension", "media_type")

    def __init__(self, config: ProfileDetectionConfig | None = None) -> None:
        self.config = config or ProfileDetectionConfig()

    def detect(
        self,
        workbook: RawWorkbook,
        profiles: Iterable[SupplierProfile],
    ) -> DetectionResult:
        scored_profiles = [
            scored
            for profile in profiles
            if (scored := self._score_profile(workbook, profile)) is not None
        ]
        scored_profiles.sort(
            key=lambda item: (-item.candidate.score, str(item.candidate.profile_id))
        )
        candidates = tuple(item.candidate for item in scored_profiles)

        if not scored_profiles:
            return DetectionResult(
                selected_profile=None,
                status=DetectionStatus.PROFILE_NOT_FOUND,
                candidates=(),
                confidence=DetectionConfidence.LOW,
                issues=(
                    self._issue(
                        ReaderIssueCode.PROFILE_NOT_FOUND,
                        "Профиль поставщика не найден",
                    ),
                ),
            )

        best = scored_profiles[0]
        if self._is_template_changed(best):
            return DetectionResult(
                selected_profile=None,
                status=DetectionStatus.TEMPLATE_CHANGED,
                candidates=candidates,
                confidence=self._confidence_without_selection(best.candidate.confidence),
                issues=(
                    self._issue(
                        ReaderIssueCode.TEMPLATE_CHANGED,
                        "Поставщик найден, но структура файла не соответствует активному профилю",
                        details={
                            "profileId": str(best.candidate.profile_id),
                            "totalScore": f"{best.candidate.total_score:.2f}",
                        },
                    ),
                ),
            )
        if best.candidate.score < self.config.selection_threshold:
            return DetectionResult(
                selected_profile=None,
                status=DetectionStatus.PROFILE_NOT_FOUND,
                candidates=candidates,
                confidence=self._confidence_without_selection(best.candidate.confidence),
                issues=(
                    self._issue(
                        ReaderIssueCode.PROFILE_NOT_FOUND,
                        "Ни один профиль не достиг порога автоматического выбора",
                        details={
                            "bestScore": f"{best.candidate.score:.6f}",
                            "selectionThreshold": f"{self.config.selection_threshold:.6f}",
                        },
                    ),
                ),
            )

        if len(scored_profiles) > 1:
            second = scored_profiles[1]
            score_gap = best.candidate.score - second.candidate.score
            if score_gap < self.config.ambiguity_margin:
                return DetectionResult(
                    selected_profile=None,
                    status=DetectionStatus.AMBIGUOUS_PROFILE,
                    candidates=candidates,
                    confidence=self._confidence_without_selection(best.candidate.confidence),
                    issues=(
                        self._issue(
                            ReaderIssueCode.AMBIGUOUS_PROFILE,
                            "Несколько профилей имеют близкие технические оценки",
                            details={
                                "bestProfileId": str(best.candidate.profile_id),
                                "bestScore": f"{best.candidate.score:.6f}",
                                "secondProfileId": str(second.candidate.profile_id),
                                "secondScore": f"{second.candidate.score:.6f}",
                                "scoreGap": f"{score_gap:.6f}",
                            },
                        ),
                    ),
                )

        return DetectionResult(
            selected_profile=best.profile,
            status=DetectionStatus.MATCHED,
            candidates=candidates,
            confidence=best.candidate.confidence,
        )

    @staticmethod
    def _confidence_without_selection(
        confidence: DetectionConfidence,
    ) -> DetectionConfidence:
        """Keep an unresolved result from claiming high confidence."""

        return DetectionConfidence.MEDIUM if confidence is DetectionConfidence.HIGH else confidence

    def _score_profile(
        self,
        workbook: RawWorkbook,
        profile: SupplierProfile,
    ) -> _ScoredProfile | None:
        if profile.status.value != "ACTIVE" or profile.active_version is None:
            return None

        version = profile.active_version
        best: _ScoredProfile | None = None
        for file_rule in version.file_rules:
            fingerprint = self._profile_fingerprint(version, file_rule)
            column_score, column_reason = self._column_score(workbook, fingerprint)
            component_scores = {
                "filename": self._filename_score(workbook, fingerprint),
                "sheet": self._sheet_score(workbook, fingerprint),
                "columns": column_score,
                "extension": self._extension_score(workbook, fingerprint),
                "media_type": self._media_type_score(workbook, fingerprint),
            }
            active_features = [
                feature
                for feature in self._FEATURES
                if self._feature_is_declared(feature, fingerprint)
                and self.config.weights.for_feature(feature) > 0.0
            ]
            denominator = sum(
                self.config.weights.for_feature(feature) for feature in active_features
            )
            if denominator == 0.0:
                continue
            component_points = {
                feature: round(
                    component_scores[feature]
                    * self.config.weights.for_feature(feature)
                    / denominator
                    * 100.0,
                    2,
                )
                for feature in active_features
            }
            component_weights = {
                feature: round(
                    self.config.weights.for_feature(feature) / denominator * 100.0,
                    2,
                )
                for feature in active_features
            }
            total_score = round(sum(component_points.values()), 2)
            reasons = tuple(
                self._reason(feature, component_scores[feature], file_rule, column_reason)
                for feature in active_features
            )
            component_names = {
                "filename": "filename",
                "sheet": "sheets",
                "columns": "columns",
                "extension": "extension",
                "media_type": "mediaType",
            }
            candidate = ProfileMatchCandidate(
                profile_id=profile.id,
                version=version.version_number,
                total_score=total_score,
                confidence=confidence_for_score(
                    total_score / 100.0,
                    high_threshold=self.config.high_confidence_threshold,
                    medium_threshold=self.config.medium_confidence_threshold,
                ),
                fingerprint=fingerprint,
                reasons=reasons,
                score_components={
                    component_names[feature]: ScoreComponent(
                        score=component_points.get(feature, 0.0),
                        weight=component_weights.get(feature, 0.0),
                    )
                    for feature in self._FEATURES
                },
            )
            current = _ScoredProfile(
                profile=profile,
                candidate=candidate,
                component_ratios=component_scores,
            )
            if best is None or candidate.score > best.candidate.score:
                best = current

        return best if best is not None and best.candidate.score > 0.0 else None

    @staticmethod
    def _feature_is_declared(
        feature: str,
        fingerprint: ProfileFingerprint,
    ) -> bool:
        if feature == "filename":
            return fingerprint.filename_pattern is not None
        if feature == "sheet":
            return bool(fingerprint.sheet_names)
        if feature == "columns":
            return bool(fingerprint.column_names)
        if feature == "extension":
            return bool(fingerprint.extensions)
        if feature == "media_type":
            return bool(fingerprint.media_types)
        raise ValueError(f"Unknown feature: {feature}")

    @staticmethod
    def _profile_fingerprint(
        version: SupplierProfileVersion,
        file_rule: SupplierFileRule,
    ) -> ProfileFingerprint:
        sheet_names = file_rule.expected_sheets or tuple(
            mapping.sheet_name for mapping in version.sheet_mappings if mapping.required
        )
        return ProfileFingerprint(
            filename_pattern=file_rule.filename_pattern,
            extensions=tuple(item.casefold() for item in file_rule.extensions),
            media_types=tuple(
                item.split(";", 1)[0].strip().casefold() for item in file_rule.media_types
            ),
            sheet_names=tuple(SupplierProfileDetector._normalize(item) for item in sheet_names),
            column_names=tuple(
                SupplierProfileDetector._normalize(mapping.source_column)
                for mapping in version.column_mappings
            ),
        )

    @staticmethod
    def _filename_score(workbook: Workbook, fingerprint: ProfileFingerprint) -> float:
        pattern = fingerprint.filename_pattern
        if pattern is None:
            return 0.0
        filename = SupplierProfileDetector._basename(workbook.filename.name)
        glob_pattern = pattern.casefold()
        if fnmatchcase(filename.casefold(), glob_pattern):
            return 1.0
        try:
            return 1.0 if re.search(pattern, filename, flags=re.IGNORECASE) is not None else 0.0
        except re.error:
            return 0.0

    @staticmethod
    def _extension_score(workbook: Workbook, fingerprint: ProfileFingerprint) -> float:
        extension = SupplierProfileDetector._extension(workbook.filename.name)
        expected = set(fingerprint.extensions)
        return 1.0 if extension is not None and extension.casefold() in expected else 0.0

    @staticmethod
    def _media_type_score(workbook: Workbook, fingerprint: ProfileFingerprint) -> float:
        media_type = workbook.filename.media_type
        if media_type is None:
            return 0.0
        normalized = media_type.split(";", 1)[0].strip().casefold()
        expected = set(fingerprint.media_types)
        return 1.0 if normalized in expected else 0.0

    @staticmethod
    def _sheet_score(
        workbook: Workbook,
        fingerprint: ProfileFingerprint,
    ) -> float:
        if not fingerprint.sheet_names:
            return 0.0
        actual_names = {SupplierProfileDetector._normalize(sheet.name) for sheet in workbook.sheets}
        expected = set(fingerprint.sheet_names)
        return len(expected & actual_names) / len(expected)

    @staticmethod
    def _column_score(
        workbook: Workbook,
        fingerprint: ProfileFingerprint,
    ) -> tuple[float, str]:
        expected = set(fingerprint.column_names)
        if not expected:
            return 0.0, "columns: no declared columns"

        best_matches: set[str] = set()
        for sheet in workbook.sheets:
            for row in sheet.rows:
                values = {
                    SupplierProfileDetector._normalize(value)
                    for value in (SupplierProfileDetector._cell_text(cell) for cell in row.cells)
                    if value is not None and value.strip()
                }
                matches = expected & values
                if len(matches) > len(best_matches):
                    best_matches = matches
        score = len(best_matches) / len(expected)
        return score, f"columns: {len(best_matches)}/{len(expected)} matched"

    def _is_template_changed(self, scored: _ScoredProfile) -> bool:
        fingerprint = scored.candidate.fingerprint
        ratios = scored.component_ratios
        if fingerprint.filename_pattern is None or ratios["filename"] < 1.0:
            return False
        declared_format = [
            feature
            for feature, values in (
                ("extension", fingerprint.extensions),
                ("media_type", fingerprint.media_types),
            )
            if values
        ]
        if declared_format and not any(ratios[feature] == 1.0 for feature in declared_format):
            return False
        structural = [
            feature
            for feature, values in (
                ("sheet", fingerprint.sheet_names),
                ("columns", fingerprint.column_names),
            )
            if values and self.config.weights.for_feature(feature) > 0.0
        ]
        if not structural:
            return False
        denominator = sum(self.config.weights.for_feature(feature) for feature in structural)
        compatibility = (
            sum(
                ratios[feature] * self.config.weights.for_feature(feature) for feature in structural
            )
            / denominator
        )
        return compatibility < self.config.structural_compatibility_threshold

    @staticmethod
    def _cell_text(cell: object) -> str | None:
        raw_value = getattr(cell, "raw_value", None)
        if isinstance(raw_value, str):
            return raw_value
        display_value = getattr(cell, "display_value", None)
        return display_value if isinstance(display_value, str) else None

    @staticmethod
    def _reason(
        feature: str,
        score: float,
        file_rule: SupplierFileRule,
        column_reason: str,
    ) -> str:
        if feature == "columns":
            return column_reason
        label = {
            "filename": "filename pattern",
            "sheet": "sheet names",
            "extension": "extension",
            "media_type": "media type",
        }[feature]
        return f"{label}: {'matched' if score == 1.0 else 'not matched'}"

    @staticmethod
    def _basename(filename: str) -> str:
        return filename.replace("\\", "/").rsplit("/", 1)[-1]

    @staticmethod
    def _extension(filename: str) -> str | None:
        basename = SupplierProfileDetector._basename(filename)
        if "." not in basename or basename.endswith("."):
            return None
        return "." + basename.rsplit(".", 1)[1]

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().strip().split())

    @staticmethod
    def _issue(
        code: ReaderIssueCode,
        message: str,
        *,
        details: dict[str, str] | None = None,
    ) -> ReaderIssue:
        return ReaderIssue(
            issue_id=f"profile-detection-{code.value.lower()}",
            code=code,
            severity=IssueSeverity.ERROR,
            message=message,
            details=details or {},
        )


ProfileDetector = SupplierProfileDetector


__all__ = [
    "ProfileDetectionConfig",
    "ProfileDetectionWeights",
    "ProfileDetector",
    "SupplierProfileDetector",
]
