import ast
import re

import yaml
from dataclasses import dataclass, field
from typing import List
from pathlib import Path
from radon.complexity import cc_visit

from automation.quality import QualityIssue, QualityReport
from automation.quality.patterns import PatternDetector


class CodeQualityScanner:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.rules = self._load_rules()
        self._rules_loaded = True
        self._pattern_detector = PatternDetector()
    
    @property
    def rules_loaded(self) -> bool:
        return self._rules_loaded
    
    def _load_rules(self) -> dict:
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _analyze_complexity(self, filepath: str, source: str) -> List[QualityIssue]:
        """Analyze cyclomatic complexity of Python source code."""
        issues: List[QualityIssue] = []
        max_complexity = self.rules['rules']['complexity']['max_cyclomatic']
        
        try:
            results = cc_visit(source)
            for result in results:
                if result.complexity > max_complexity:
                    issues.append(QualityIssue(
                        file=filepath,
                        line=result.lineno,
                        rule="complexity.cyclomatic",
                        severity="warning",
                        message=f"Function '{result.name}' has cyclomatic complexity {result.complexity} (max: {max_complexity})"
                    ))
        except Exception:
            # Skip files that can't be parsed
            pass
        
        return issues
    
    def _check_architecture(self, filepath: str, source: str) -> List[QualityIssue]:
        """Check for forbidden architectural dependencies."""
        issues: List[QualityIssue] = []
        forbidden = self.rules['rules']['architecture'].get('forbidden_dependencies', [])
        
        try:
            tree = ast.parse(source)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for rule in forbidden:
                        from_pattern = rule['from'].replace('*', '.*')
                        to_pattern = rule['to'].replace('*', '.*')
                        
                        # Check if this import matches a forbidden pattern
                        if re.match(from_pattern, module):
                            for name in node.names:
                                full_import = f"{module}.{name.name}"
                                # Check if importing from forbidden target
                                target_module = to_pattern.replace('from ', '')
                                if re.match(target_module, full_import) or re.match(target_module, module):
                                    issues.append(QualityIssue(
                                        file=filepath,
                                        line=node.lineno,
                                        rule="architecture.forbidden_dependency",
                                        severity="error",
                                        message=f"Forbidden dependency: {module} -> {name.name}"
                                    ))
        except Exception:
            pass
        
        return issues
    
    def _detect_patterns(self, filepath: str, source: str) -> List[QualityIssue]:
        """Detect code anti-patterns."""
        return self._pattern_detector.detect_patterns(filepath, source)
    
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
            issues.extend(self._analyze_complexity(str(file), source))
            issues.extend(self._check_architecture(str(file), source))
            issues.extend(self._detect_patterns(str(file), source))
        
        return QualityReport(
            issues=issues,
            files_scanned=files_scanned,
            rules_violated=len(set(i.rule for i in issues)),
            overall_score=max(0.0, 100.0 - len(issues) * 2)
        )
