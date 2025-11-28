#!/bin/bash
# BirdNET-PiPy Installation Script (Legacy Wrapper)
# This script is maintained for backwards compatibility
# It redirects to the unified install.sh in the repository root
#
# IMPORTANT: For new installations, use the unified installer:
#   sudo ./install.sh  (from repository root)
#
# Or via curl:
#   curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}[NOTICE]${NC} This script (deployment/install-service.sh) is now a legacy wrapper"
echo -e "${GREEN}[INFO]${NC} Redirecting to unified install.sh..."
echo ""

# Check if unified installer exists
if [ ! -f "$PROJECT_ROOT/install.sh" ]; then
    echo -e "${RED}[ERROR]${NC} Unified installer not found: $PROJECT_ROOT/install.sh"
    echo -e "${YELLOW}[INFO]${NC} Please update your repository: git pull origin main"
    exit 1
fi

# Make it executable
chmod +x "$PROJECT_ROOT/install.sh"

# Execute the unified installer with all passed arguments
exec "$PROJECT_ROOT/install.sh" "$@"
