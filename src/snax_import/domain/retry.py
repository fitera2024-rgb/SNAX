from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from snax_import.domain.errors import InvalidValue, RetryBudgetExhausted


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_seconds: float
    max_seconds: float
    multiplier: float
    jitter_ratio: float
    random_value: Callable[[], float]

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise InvalidValue("maxAttempts", "Max attempts должен быть >= 1")
        if self.base_seconds <= 0 or self.max_seconds <= 0 or self.multiplier < 1:
            raise InvalidValue("retry", "Backoff values должны быть положительными")
        if not 0 <= self.jitter_ratio <= 1:
            raise InvalidValue("jitterRatio", "Jitter ratio должен быть между 0 и 1")

    def delay_seconds(self, attempt_number: int) -> float:
        if attempt_number < 1 or attempt_number >= self.max_attempts:
            raise RetryBudgetExhausted()
        raw = min(self.max_seconds, self.base_seconds * self.multiplier ** (attempt_number - 1))
        sample = self.random_value()
        if not 0 <= sample <= 1:
            raise InvalidValue("randomValue", "Random source должен возвращать 0..1")
        jitter = raw * self.jitter_ratio * ((sample * 2) - 1)
        return max(0.0, min(self.max_seconds, raw + jitter))
