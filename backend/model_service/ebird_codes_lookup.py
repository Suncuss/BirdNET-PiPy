"""Standalone eBird species code lookup.

Reads ``ebird_codes.json`` (a flat ``{sci_name: ebird_code}`` mapping) into
memory on first access. Kept separate from ``label_utils`` so the inference
server doesn't have to load the full multi-language species table just to
attach an eBird code to each detection.
"""

import json
import logging
import sys
import threading

logger = logging.getLogger(__name__)

_ebird_codes: dict[str, str] | None = None
_loading_lock = threading.Lock()


def _ensure_loaded() -> None:
    """Load eBird codes on first access (thread-safe)."""
    global _ebird_codes
    if _ebird_codes is not None:
        return

    with _loading_lock:
        if _ebird_codes is not None:
            return

        from config import settings

        codes: dict[str, str] = {}
        try:
            with open(settings.EBIRD_CODES_PATH, encoding='utf-8') as f:
                raw = json.load(f)
            for sci, code in raw.items():
                codes[sys.intern(sci)] = sys.intern(code)
            logger.info(
                "Loaded eBird codes",
                extra={'species_count': len(codes)},
            )
        except Exception:
            logger.exception(
                "Failed to load eBird codes from %s", settings.EBIRD_CODES_PATH
            )

        _ebird_codes = codes


def get_ebird_code(sci_name: str) -> str | None:
    """Look up the eBird species code for a scientific name."""
    _ensure_loaded()
    return _ebird_codes.get(sci_name) or None


def clear_ebird_codes_cache() -> None:
    """Reset the loaded eBird codes. Used by tests."""
    global _ebird_codes
    _ebird_codes = None
