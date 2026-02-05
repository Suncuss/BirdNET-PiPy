#!/bin/bash
# Run linters inside Docker containers
# Checks both frontend (ESLint) and backend (Ruff)

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Track if any linter fails
FRONTEND_FAILED=false
BACKEND_FAILED=false

# Parse arguments
FIX_MODE=false
FRONTEND_ONLY=false
BACKEND_ONLY=false

for arg in "$@"; do
    case $arg in
        --fix)
            FIX_MODE=true
            ;;
        --frontend)
            FRONTEND_ONLY=true
            ;;
        --backend)
            BACKEND_ONLY=true
            ;;
        --help)
            echo "Usage: ./docker-lint.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --fix       Auto-fix issues where possible"
            echo "  --frontend  Only lint frontend"
            echo "  --backend   Only lint backend"
            echo "  --help      Show this help message"
            exit 0
            ;;
    esac
done

# Frontend linting
run_frontend_lint() {
    echo -e "${GREEN}[LINT]${NC} Frontend (ESLint)..."
    echo "===================================="

    local fix_flag=""
    if [ "$FIX_MODE" = true ]; then
        fix_flag="--fix"
        echo "Running with --fix enabled"
    fi

    docker run --rm \
        -v "$(pwd)/frontend:/app" \
        -w /app \
        node:20-alpine \
        sh -c "npm ci --silent && npm run lint -- $fix_flag" || FRONTEND_FAILED=true

    if [ "$FRONTEND_FAILED" = true ]; then
        echo -e "${RED}[LINT]${NC} Frontend: issues found"
    else
        echo -e "${GREEN}[LINT]${NC} Frontend: passed"
    fi
    echo ""
}

# Backend linting
run_backend_lint() {
    echo -e "${GREEN}[LINT]${NC} Backend (Ruff)..."
    echo "===================================="

    local fix_flag=""
    if [ "$FIX_MODE" = true ]; then
        fix_flag="--fix"
        echo "Running with --fix enabled"
    fi

    docker run --rm \
        -v "$(pwd)/backend:/app" \
        -w /app \
        python:3.11-slim \
        sh -c "pip install -q ruff && ruff check . $fix_flag" || BACKEND_FAILED=true

    if [ "$BACKEND_FAILED" = true ]; then
        echo -e "${RED}[LINT]${NC} Backend: issues found"
    else
        echo -e "${GREEN}[LINT]${NC} Backend: passed"
    fi
    echo ""
}

# Run linters based on flags
if [ "$BACKEND_ONLY" = true ]; then
    run_backend_lint
elif [ "$FRONTEND_ONLY" = true ]; then
    run_frontend_lint
else
    run_frontend_lint
    run_backend_lint
fi

# Summary
echo "===================================="
if [ "$FRONTEND_FAILED" = true ] || [ "$BACKEND_FAILED" = true ]; then
    echo -e "${RED}[LINT]${NC} Some checks failed"
    echo ""
    echo "To auto-fix issues, run: ./docker-lint.sh --fix"
    exit 1
else
    echo -e "${GREEN}[LINT]${NC} All checks passed"
    exit 0
fi
