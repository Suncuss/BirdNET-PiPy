#!/bin/sh
# POSIX-compatible entrypoint (no bash dependency)
set -e

SETTINGS_FILE="/app/data/config/user_settings.json"

# Read and validate timezone from settings
if [ -f "$SETTINGS_FILE" ]; then
    TZ=$(python3 -c "
import json
import sys
from zoneinfo import ZoneInfo

try:
    with open('$SETTINGS_FILE') as f:
        tz = json.load(f).get('location', {}).get('timezone')
    if tz:
        ZoneInfo(tz)  # Validate - raises if invalid
        print(tz)
    else:
        print('UTC')
except Exception as e:
    print(f'[entrypoint] Invalid timezone, using UTC: {e}', file=sys.stderr)
    print('UTC')
")
else
    TZ="UTC"
fi

export TZ
echo "[entrypoint] Timezone: $TZ"

exec "$@"
