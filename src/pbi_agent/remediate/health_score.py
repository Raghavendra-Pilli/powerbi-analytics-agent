"""Report Health Score — a simple, transparent 0-100 score derived from the
rule-based inspection findings.

Formula (documented, not hidden):
    score = 100 - (errors * 8) - (warnings * 3) - (info * 0.5)
    clamped to [0, 100]

Errors are weighted heaviest since they represent broken/non-functional
parts of the model (e.g. a measure with no DAX expression at all).
"""

from __future__ import annotations

from dataclasses import dataclass

ERROR_WEIGHT = 8.0
WARNING_WEIGHT = 3.0
INFO_WEIGHT = 0.5


@dataclass
class HealthScore:
    score: float
    errors: int
    warnings: int
    info: int

    @property
    def grade(self) -> str:
        if self.score >= 90:
            return "A"
        if self.score >= 75:
            return "B"
        if self.score >= 60:
            return "C"
        if self.score >= 40:
            return "D"
        return "F"

    def __str__(self) -> str:
        return f"{self.score:.0f}/100 (grade {self.grade})"


def calculate_health_score(counts: dict) -> HealthScore:
    """Compute a health score from an inspection result's counts dict
    (as returned by ModelInspector.inspect()['counts'])."""
    errors = counts.get("errors", 0)
    warnings = counts.get("warnings", 0)
    info = counts.get("info", 0)

    raw = 100.0 - (errors * ERROR_WEIGHT) - (warnings * WARNING_WEIGHT) - (info * INFO_WEIGHT)
    score = max(0.0, min(100.0, raw))

    return HealthScore(score=score, errors=errors, warnings=warnings, info=info)
