#!/bin/bash
# Run tests for BirdNET-PiPy backend (docker-test.sh runs this in the test
# container). The first argument picks what to run:
#   (none) | db | database | api | integration | coverage | <test path>
# A second argument of "coverage" adds a coverage report; anything after that
# is passed to pytest.

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting BirdNET-PiPy Test Suite${NC}"
echo "=================================="

COVERAGE_MODE=false
case "$1" in
    db|database)
        TEST_PATH="tests/database/"
        echo -e "${YELLOW}Running database tests only...${NC}" ;;
    api)
        TEST_PATH="tests/api/"
        echo -e "${YELLOW}Running API tests only...${NC}" ;;
    integration)
        TEST_PATH="tests/integration/"
        echo -e "${YELLOW}Running integration tests only...${NC}" ;;
    coverage)
        TEST_PATH="tests/"
        COVERAGE_MODE=true ;;
    "")
        TEST_PATH="tests/" ;;
    *)
        TEST_PATH="$1" ;;
esac
[ $# -gt 0 ] && shift
if [[ "$1" == "coverage" ]]; then
    COVERAGE_MODE=true
    shift
fi

COVERAGE_ARGS=()
if [ "$COVERAGE_MODE" = true ]; then
    echo -e "${GREEN}Coverage mode enabled${NC}"
    COVERAGE_ARGS=(--cov=core --cov=model_service
                   --cov-report=term-missing:skip-covered
                   --cov-report=html --cov-report=term)
fi

python -m pytest "$TEST_PATH" "${COVERAGE_ARGS[@]}" -v --tb=short "$@"

if [ "$COVERAGE_MODE" = true ]; then
    echo -e "${GREEN}Coverage HTML report generated in htmlcov/${NC}"
    echo -e "${GREEN}Open htmlcov/index.html in your browser to view detailed coverage${NC}"
fi
echo -e "\n${GREEN}✓ All tests passed!${NC}"
