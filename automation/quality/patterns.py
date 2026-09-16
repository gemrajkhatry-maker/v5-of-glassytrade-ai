from __future__ import annotations

import ast
from typing import List

from automation.quality import QualityIssue


class PatternDetector:
    """Detects common code anti-patterns using AST analysis."""

    def detect_patterns(self, filepath: str, source: str) -> List[QualityIssue]:
        """Detect all anti-patterns in the source code."""
        issues: List[QualityIssue] = []

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return issues

        issues.extend(self._detect_bare_except(filepath, tree))
        issues.extend(self._detect_silent_except_pass(filepath, tree, source))
        issues.extend(self._detect_mutable_defaults(filepath, tree))
        issues.extend(self._detect_unused_imports(filepath, tree, source))

        return issues

    def _detect_bare_except(self, filepath: str, tree: ast.AST) -> List[QualityIssue]:
        """Detect bare except clauses (except: instead of except Exception:)."""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    issues.append(QualityIssue(
                        file=filepath,
                        line=node.lineno,
                        rule="pattern.bare_except",
                        severity="warning",
                        message="Bare except clause — use 'except Exception:' instead"
                    ))
        return issues

    def _detect_silent_except_pass(
        self, filepath: str, tree: ast.AST, source: str
    ) -> List[QualityIssue]:
        """Detect except blocks that only contain 'pass' (silent error swallowing)."""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)):
                    issues.append(QualityIssue(
                        file=filepath,
                        line=node.lineno,
                        rule="pattern.silent_except_pass",
                        severity="warning",
                        message="Silent except:pass — errors are swallowed without logging"
                    ))
        return issues

    def _detect_mutable_defaults(
        self, filepath: str, tree: ast.AST
    ) -> List[QualityIssue]:
        """Detect functions with mutable default arguments (list, dict, set)."""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append(QualityIssue(
                            file=filepath,
                            line=node.lineno,
                            rule="pattern.mutable_default",
                            severity="error",
                            message=f"Function '{node.name}' has mutable default argument"
                        ))
        return issues

    def _detect_unused_imports(
        self, filepath: str, tree: ast.AST, source: str
    ) -> List[QualityIssue]:
        """Detect imports that are never used in the source."""
        issues = []

        # Collect all imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, node.lineno))

        # Check if each import is used
        source_lines = source.split('\n')
        for name, line_no in imports:
            # Simple heuristic: check if name appears in source (excluding import lines)
            used = False
            for i, line in enumerate(source_lines, 1):
                if i == line_no:
                    continue  # Skip the import line itself
                if name in line and not line.strip().startswith(('import ', 'from ')):
                    used = True
                    break

            if not used:
                issues.append(QualityIssue(
                    file=filepath,
                    line=line_no,
                    rule="pattern.unused_import",
                    severity="info",
                    message=f"Import '{name}' appears unused"
                ))

        return issues
