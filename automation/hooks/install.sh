#!/bin/bash
# Install git hooks for automated quality checks

set -e

HOOKS_DIR=".git/hooks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Installing git hooks..."

# Create hooks directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/$HOOKS_DIR"

# Install pre-commit hook
PRE_COMMIT="$PROJECT_ROOT/$HOOKS_DIR/pre-commit"
cat > "$PRE_COMMIT" << 'EOF'
#!/bin/bash
# Pre-commit hook: run quality checks

cd "$(git rev-parse --show-toplevel)"
python automation/hooks/pre_commit.py
exit $?
EOF

chmod +x "$PRE_COMMIT"

echo "✅ Pre-commit hook installed at $PRE_COMMIT"
echo ""
echo "The hook will run quality checks on every commit."
echo "To bypass: git commit --no-verify"
