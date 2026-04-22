#!/bin/bash
# QUICK TEST EXECUTION SCRIPT
# Run immediately to validate critical fixes

set -e

echo "========================================"
echo "Running Critical Tests - Production Safety Check"
echo "========================================"

cd "$(dirname "$0")"

# Create test files if they don't exist
create_test_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "Creating $file..."
        cat > "$file" << 'TESTEOF'
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root))
TESTEOF
    fi
}

# Create all test files
create_test_file "appv2/backend/tests/test_stream_manager.py"
create_test_file "appv2/backend/tests/test_dhan_feed.py"
create_test_file "appv2/backend/tests/test_event_bus.py"
create_test_file "appv2/backend/tests/test_state_broadcaster.py"
create_test_file "appv2/backend/tests/test_state_snapshot.py"
create_test_file "appv2/backend/tests/test_api_contracts.py"
create_test_file "appv2/backend/tests/test_e2e_tick_flow.py"
create_test_file "appv2/backend/tests/test_empty_data_handling.py"
create_test_file "appv2/backend/tests/test_input_validation.py"

# Install dependencies
echo "Installing test dependencies..."
pip install pytest pytest-asyncio -q 2>/dev/null || pip3 install pytest pytest-asyncio -q

# Run critical tests
echo ""
echo "=== StreamManager Tests ==="
pytest appv2/backend/tests/test_stream_manager.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== DhanFeed Tests ==="
pytest appv2/backend/tests/test_dhan_feed.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== EventBus Tests ==="
pytest appv2/backend/tests/test_event_bus.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== StateBroadcaster Tests ==="
pytest appv2/backend/tests/test_state_broadcaster.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== StateSnapshot Tests ==="
pytest appv2/backend/tests/test_state_snapshot.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== API Contract Tests ==="
pytest appv2/backend/tests/test_api_contracts.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== E2E Tick Flow Tests ==="
pytest appv2/backend/tests/test_e2e_tick_flow.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== Empty Data Handling Tests ==="
pytest appv2/backend/tests/test_empty_data_handling.py -v --tb=short 2>&1 | tail -20

echo ""
echo "=== Input Validation Tests ==="
pytest appv2/backend/tests/test_input_validation.py -v --tb=short 2>&1 | tail -20

echo ""
echo "========================================"
echo "Test execution complete."
echo "========================================"

# Check for failures
FAILURES=0
for test_file in test_stream_manager test_dhan_feed test_event_bus test_state_broadcaster test_state_snapshot test_api_contracts test_e2e_tick_flow test_empty_data_handling test_input_validation; do
    RESULT=$(pytest "appv2/backend/tests/${test_file}.py" -q 2>&1 | tail -3)
    if echo "$RESULT" | grep -q "FAILED\|ERROR"; then
        echo "❌ FAILED: ${test_file}.py"
        FAILURES=$((FAILURES + 1))
    else
        echo "✅ PASSED: ${test_file}.py"
    fi
done

echo ""
if [ $FAILURES -eq 0 ]; then
    echo "🎉 ALL CRITICAL TESTS PASSED"
    exit 0
else
    echo "⚠️  $FAILURES TEST(S) FAILED - REVIEW REQUIRED"
    exit 1
fi