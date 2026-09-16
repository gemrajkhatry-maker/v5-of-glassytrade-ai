import yaml
from dataclasses import dataclass, field
from typing import List
from pathlib import Path


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


class CodeQualityScanner:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.rules = self._load_rules()
        self._rules_loaded = True
    
    @property
    def rules_loaded(self) -> bool:
        return self._rules_loaded
    
    def _load_rules(self) -> dict:
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def scan(self, path: str) -> QualityReport:
        """Scan a file or directory for quality issues."""
        issues: List[QualityIssue] = []
        files_scanned = 0
        
        path_obj = Path(path)
        if path_obj.is_file():
            files = [path_obj]
        else:
            files = list(path_obj.rglob("*.py"))
        
        for file in files:
            files_scanned += 1
            source = file.read_text()
            # Analysis methods will be added in later tasks
        
        return QualityReport(
            issues=issues,
            files_scanned=files_scanned,
            rules_violated=len(set(i.rule for i in issues)),
            overall_score=max(0.0, 100.0 - len(issues) * 2)
        )
