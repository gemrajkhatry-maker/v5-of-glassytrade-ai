#!/bin/bash
# Run Live Options Analytics Tests
# 
# Usage:
#   ./run_options_live_tests.sh                    # Skip all tests (no credentials)
#   ./run_options_live_tests.sh --run              # Run with credentials
#   ./run_options_live_tests.sh --help             # Show help
#
# Environment variables required:
#   DHAN_CLIENT_ID     - Your DhanHQ client ID
#   DHAN_ACCESS_TOKEN  - Your DhanHQ access token

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
show_help() {
    echo -e "${GREEN}Live Options Analytics Tests Runner${NC}"
    echo ""
    echo "Usage:"
    echo "  $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --run              Run tests with credentials"
    echo "  --help             Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  DHAN_CLIENT_ID     Your DhanHQ client ID"
    echo "  DHAN_ACCESS_TOKEN  Your DhanHQ access token"
    echo ""
    echo "Examples:"
    echo "  # Just verify tests load (will skip)"
    echo "  $0"
    echo ""
    echo "  # Run with credentials"
    echo "  export DHAN_CLIENT_ID='your_id'"
    echo "  export DHAN_ACCESS_TOKEN='your_token'"
    echo "  $0 --run"
    echo ""
}

check_credentials() {
    if [ -z "$DHAN_CLIENT_ID" ] || [ -z "$DHAN_ACCESS_TOKEN" ]; then
        echo -e "${YELLOW}⚠️  No credentials found${NC}"
        echo ""
        echo "Tests will be skipped. To run tests, set:"
        echo "  export DHAN_CLIENT_ID='your_client_id'"
        echo "  export DHAN_ACCESS_TOKEN='your_access_token'"
        echo ""
        return 1
    fi
    return 0
}

run_tests() {
    local test_file="brokersv2/tests/integration/test_options_live_validation.py"
    
    echo -e "${GREEN}🚀 Running Live Options Analytics Tests${NC}"
    echo ""
    
    # Change to project root
    cd "$(dirname "$0")/.."
    
    if check_credentials; then
        echo -e "${GREEN}✓ Credentials found${NC}"
        export RUN_OPTIONS_LIVE_TESTS=1
        echo -e "${GREEN}✓ Live tests enabled${NC}"
        echo ""
        echo -e "${YELLOW}Running 13 comprehensive options tests...${NC}"
        echo ""
        
        # Run tests
        venv/bin/python -m pytest "$test_file" -v --tb=short
        
        echo ""
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✅ All tests passed!${NC}"
        else
            echo -e "${RED}❌ Some tests failed${NC}"
            echo ""
            echo "Common issues:"
            echo "  - Invalid credentials"
            echo "  - Market closed (some tests need live data)"
            echo "  - API rate limiting"
            echo "  - Network connectivity"
        fi
    else
        echo -e "${YELLOW}⚠️  Running in check mode (tests will skip)${NC}"
        echo ""
        
        # Run tests (will skip)
        venv/bin/python -m pytest "$test_file" -v
        
        echo ""
        echo -e "${GREEN}✓ Tests loaded successfully${NC}"
        echo "  Set credentials and use --run to execute tests"
    fi
}

# Parse arguments
case "${1:-}" in
    --run)
        run_tests
        ;;
    --help|-h)
        show_help
        ;;
    *)
        run_tests
        ;;
esac
