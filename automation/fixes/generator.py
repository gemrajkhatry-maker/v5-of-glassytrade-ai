import ast
import re
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

from automation.quality import QualityIssue


@dataclass
class FixProposal:
    """A proposed fix for a quality issue."""
    issue: QualityIssue
    original_code: str
    fixed_code: str
    description: str
    confidence: float  # 0.0 to 1.0
    
    @property
    def is_safe(self) -> bool:
        """Whether this fix is safe to apply automatically."""
        return self.confidence >= 0.9


class FixGenerator:
    """Generates automated fixes for quality issues."""
    
    # Rules that can be auto-fixed
    AUTO_FIXABLE_RULES = {
        "pattern.unused_import",
        "pattern.mutable_default",
    }
    
    def generate_fixes(
        self, issues: List[QualityIssue], source: str
    ) -> List[FixProposal]:
        """Generate fix proposals for the given issues."""
        proposals = []
        
        for issue in issues:
            if issue.rule not in self.AUTO_FIXABLE_RULES:
                continue
            
            proposal = self._generate_fix(issue, source)
            if proposal:
                proposals.append(proposal)
        
        return proposals
    
    def _generate_fix(
        self, issue: QualityIssue, source: str
    ) -> Optional[FixProposal]:
        """Generate a fix for a single issue."""
        if issue.rule == "pattern.unused_import":
            return self._fix_unused_import(issue, source)
        elif issue.rule == "pattern.mutable_default":
            return self._fix_mutable_default(issue, source)
        return None
    
    def _fix_unused_import(
        self, issue: QualityIssue, source: str
    ) -> Optional[FixProposal]:
        """Remove an unused import."""
        lines = source.split('\n')
        if issue.line < 1 or issue.line > len(lines):
            return None
        
        line = lines[issue.line - 1]
        
        # Extract the import name from the message
        match = re.search(r"Import '(\w+)'", issue.message)
        if not match:
            return None
        
        import_name = match.group(1)
        
        # Check if it's a simple import line
        if line.strip().startswith('import ') or line.strip().startswith('from '):
            # For simple cases, remove the entire line
            fixed_lines = lines[:issue.line - 1] + lines[issue.line:]
            fixed_code = '\n'.join(fixed_lines)
            
            return FixProposal(
                issue=issue,
                original_code=source,
                fixed_code=fixed_code,
                description=f"Remove unused import '{import_name}'",
                confidence=0.95,
            )
        
        return None
    
    def _fix_mutable_default(
        self, issue: QualityIssue, source: str
    ) -> Optional[FixProposal]:
        """Replace mutable default with None and add initialization in function body."""
        lines = source.split('\n')
        if issue.line < 1 or issue.line > len(lines):
            return None
        
        # Parse the function to find the mutable default
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno == issue.line:
                    # Find the mutable default
                    for i, default in enumerate(node.args.defaults):
                        if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                            # Get the parameter name
                            num_args = len(node.args.args)
                            num_defaults = len(node.args.defaults)
                            if i >= num_args - num_defaults:
                                param_idx = i - (num_args - num_defaults)
                                if param_idx < len(node.args.args):
                                    param_name = node.args.args[num_args - num_defaults + i].arg
                                    
                                    # Determine the replacement type
                                    if isinstance(default, ast.List):
                                        replacement = "None"
                                        init_code = f"    if {param_name} is None:\n        {param_name} = []"
                                    elif isinstance(default, ast.Dict):
                                        replacement = "None"
                                        init_code = f"    if {param_name} is None:\n        {param_name} = {{}}"
                                    elif isinstance(default, ast.Set):
                                        replacement = "None"
                                        init_code = f"    if {param_name} is None:\n        {param_name} = set()"
                                    else:
                                        continue
                                    
                                    # Replace in source
                                    line = lines[issue.line - 1]
                                    # Simple replacement: find "=[]" or "={}" or "=set()"
                                    pattern = rf'{param_name}\s*=\s*(\[\]|\{{\}}|set\(\))'
                                    fixed_line = re.sub(pattern, f'{param_name}={replacement}', line)
                                    lines[issue.line - 1] = fixed_line
                                    
                                    # Add initialization after def line
                                    # Find the end of the def line (after the closing paren)
                                    def_end = issue.line - 1
                                    for j in range(issue.line - 1, len(lines)):
                                        if ':' in lines[j]:
                                            def_end = j
                                            break
                                    
                                    lines.insert(def_end + 1, init_code)
                                    fixed_code = '\n'.join(lines)
                                    
                                    return FixProposal(
                                        issue=issue,
                                        original_code=source,
                                        fixed_code=fixed_code,
                                        description=f"Replace mutable default for '{param_name}' with None",
                                        confidence=0.85,
                                    )
        
        return None
    
    def apply_fix(self, proposal: FixProposal, filepath: str) -> bool:
        """Apply a fix proposal to a file."""
        if not proposal.is_safe:
            return False
        
        try:
            Path(filepath).write_text(proposal.fixed_code)
            return True
        except Exception:
            return False
