"""Runtime mode detection helpers.

Determines whether the app is running inside a Home Assistant add-on
by checking for the SUPERVISOR_TOKEN environment variable.
"""

import os

MODE_NATIVE = "native"
MODE_HOME_ASSISTANT = "ha"


def get_runtime_mode():
    """Check SUPERVISOR_TOKEN env var. No HTTP probing."""
    return MODE_HOME_ASSISTANT if os.environ.get("SUPERVISOR_TOKEN", "").strip() else MODE_NATIVE


def is_home_assistant_mode():
    return get_runtime_mode() == MODE_HOME_ASSISTANT
