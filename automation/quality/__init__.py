from dataclasses import dataclass, field
from typing import List


@dataclass
class QualityIssue:
    file: str
    line: int
    rule: str
    severity: str
    message: str


@dataclass
class QualityReport:
    issues: List[QualityIssue]
    files_scanned: int
    rules_violated: int
    overall_score: float
