#!/bin/bash
# Run tests for BirdNET-PiPy backend
# This script runs tests in a Docker-friendly way with proper Python path setup

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting BirdNET-PiPy Test Suite${NC}"
echo "=================================="

# Set Python path for imports
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Default test path
TEST_PATH="${1:-tests/}"

# Check if coverage flag is passed
COVERAGE_MODE=false
if [[ "$1" == "coverage" ]] || [[ "$2" == "coverage" ]]; then
    COVERAGE_MODE=true
    echo -e "${GREEN}Coverage mode enabled${NC}"
fi

# Check if running specific test category
if [[ "$1" == "db" ]] || [[ "$1" == "database" ]]; then
    TEST_PATH="tests/database/"
    echo -e "${YELLOW}Running database tests only...${NC}"
elif [[ "$1" == "api" ]]; then
    TEST_PATH="tests/api/"
    echo -e "${YELLOW}Running API tests only...${NC}"
elif [[ "$1" == "integration" ]]; then
    TEST_PATH="tests/integration/"
    echo -e "${YELLOW}Running integration tests only...${NC}"
elif [[ "$1" == "coverage" ]]; then
    echo -e "${YELLOW}Running all tests with coverage report...${NC}"
    python -m pytest tests/ \
        --cov=core \
        --cov=birdnet_service \
        --cov-report=term-missing:skip-covered \
        --cov-report=html \
        --cov-report=term \
        -v
    echo -e "${GREEN}Coverage HTML report generated in htmlcov/${NC}"
    echo -e "${GREEN}Open htmlcov/index.html in your browser to view detailed coverage${NC}"
    exit 0
fi

# Run tests with pytest
if command -v pytest &> /dev/null; then
    if [ "$COVERAGE_MODE" = true ]; then
        echo -e "${YELLOW}Running with coverage report...${NC}"
        # Don't pass coverage as an argument to pytest
        if [[ "$2" == "coverage" ]]; then
            EXTRA_ARGS="${@:3}"
        else
            EXTRA_ARGS="${@:2}"
        fi
        python -m pytest $TEST_PATH \
            --cov=core \
            --cov=birdnet_service \
            --cov-report=term-missing:skip-covered \
            --cov-report=html \
            --cov-report=term \
            -v --tb=short $EXTRA_ARGS
        echo -e "${GREEN}Coverage HTML report generated in htmlcov/${NC}"
        echo -e "${GREEN}Open htmlcov/index.html in your browser to view detailed coverage${NC}"
        
        # Check if htmlcov was created
        if [ -d "htmlcov" ]; then
            echo -e "${GREEN}✓ HTML coverage report successfully created${NC}"
            ls -la htmlcov/ | head -5
        else
            echo -e "${RED}✗ HTML coverage report directory not found${NC}"
        fi
    else
        python -m pytest $TEST_PATH -v --tb=short "${@:2}"
    fi
else
    echo -e "${RED}pytest not found. Installing test requirements...${NC}"
    pip install -r requirements-test.txt
    if [ "$COVERAGE_MODE" = true ]; then
        # Don't pass coverage as an argument to pytest
        if [[ "$2" == "coverage" ]]; then
            EXTRA_ARGS="${@:3}"
        else
            EXTRA_ARGS="${@:2}"
        fi
        python -m pytest $TEST_PATH \
            --cov=core \
            --cov=birdnet_service \
            --cov-report=term-missing:skip-covered \
            --cov-report=html \
            --cov-report=term \
            -v --tb=short $EXTRA_ARGS
        echo -e "${GREEN}Coverage HTML report generated in htmlcov/${NC}"
        echo -e "${GREEN}Open htmlcov/index.html in your browser to view detailed coverage${NC}"
        
        # Check if htmlcov was created
        if [ -d "htmlcov" ]; then
            echo -e "${GREEN}✓ HTML coverage report successfully created${NC}"
            ls -la htmlcov/ | head -5
        else
            echo -e "${RED}✗ HTML coverage report directory not found${NC}"
        fi
    else
        python -m pytest $TEST_PATH -v --tb=short "${@:2}"
    fi
fi

# Check test results
if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✓ All tests passed!${NC}"
else
    echo -e "\n${RED}✗ Some tests failed${NC}"
    exit 1
fi