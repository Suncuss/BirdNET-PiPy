"""Helpers for localized bird display names."""

from __future__ import annotations

from core.runtime_config import get_runtime_settings
from model_service.label_utils import (
    clear_species_cache,
    get_localized_name,
    get_localized_name_from_english,
)

DEFAULT_BIRD_NAME_LANGUAGE = 'en'

BIRD_NAME_LANGUAGE_LABELS = {
    'af': 'Afrikaans',
    'ar': 'Arabic',
    'cs': 'Czech',
    'da': 'Danish',
    'de': 'German',
    'en': 'English (US)',
    'en_uk': 'English (UK)',
    'es': 'Spanish',
    'fi': 'Finnish',
    'fr': 'French',
    'hu': 'Hungarian',
    'it': 'Italian',
    'ja': 'Japanese',
    'ko': 'Korean',
    'nl': 'Dutch',
    'no': 'Norwegian',
    'pl': 'Polish',
    'pt': 'Portuguese',
    'ro': 'Romanian',
    'ru': 'Russian',
    'sk': 'Slovak',
    'sl': 'Slovenian',
    'sv': 'Swedish',
    'th': 'Thai',
    'tr': 'Turkish',
    'uk': 'Ukrainian',
    'zh': 'Chinese',
}

SUPPORTED_BIRD_NAME_LANGUAGES = frozenset(BIRD_NAME_LANGUAGE_LABELS)
SPECTROGRAM_UNSUPPORTED_BIRD_NAME_LANGUAGES = frozenset({
    'ar',
    'ja',
    'ko',
    'th',
    'zh',
})


def normalize_bird_name_language(language: str | None) -> str:
    """Return a supported bird-name language code."""
    if language in SUPPORTED_BIRD_NAME_LANGUAGES:
        return language
    return DEFAULT_BIRD_NAME_LANGUAGE


def get_bird_name_language(settings: dict | None = None) -> str:
    """Read the preferred bird-name language from settings."""
    settings_data = settings or get_runtime_settings()
    display = settings_data.get('display', {})
    return normalize_bird_name_language(display.get('bird_name_language'))


def _resolve_language(language: str | None, settings: dict | None) -> str:
    if language:
        return normalize_bird_name_language(language)
    return get_bird_name_language(settings)


def clear_bird_name_caches() -> None:
    """Clear cached label mappings."""
    clear_species_cache()


def get_localized_common_name(
    scientific_name: str | None,
    common_name: str | None = None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> str:
    """Return a localized display name for a species."""
    lang = _resolve_language(language, settings)

    if scientific_name:
        localized = get_localized_name(scientific_name, lang)
        if localized:
            return localized

    return common_name or scientific_name or ''


def get_localized_common_name_from_english(
    common_name: str | None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> str:
    """Return a localized display name when only the English common name is known."""
    if not common_name:
        return ''

    lang = _resolve_language(language, settings)
    localized = get_localized_name_from_english(common_name, lang)
    return localized if localized else common_name


def should_use_localized_spectrogram_titles(
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> bool:
    """Return whether the bundled spectrogram font can safely render localized titles."""
    lang = _resolve_language(language, settings)
    return lang not in SPECTROGRAM_UNSUPPORTED_BIRD_NAME_LANGUAGES


def get_spectrogram_common_name(
    scientific_name: str | None,
    common_name: str | None = None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> str:
    """Return the bird name to use in spectrogram titles."""
    if not should_use_localized_spectrogram_titles(
        language=language,
        settings=settings,
    ):
        return common_name or scientific_name or ''

    return get_localized_common_name(
        scientific_name,
        common_name,
        language=language,
        settings=settings,
    )


def get_spectrogram_common_name_from_english(
    common_name: str | None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> str:
    """Return the English or localized bird name to use in spectrogram titles."""
    if not should_use_localized_spectrogram_titles(
        language=language,
        settings=settings,
    ):
        return common_name or ''

    return get_localized_common_name_from_english(
        common_name,
        language=language,
        settings=settings,
    )


def add_display_common_name(
    data: dict | None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> dict | None:
    """Return a copy with display_common_name attached."""
    if not data:
        return data

    localized = get_localized_common_name(
        data.get('scientific_name'),
        data.get('common_name'),
        language=language,
        settings=settings,
    )

    enriched = dict(data)
    enriched['display_common_name'] = localized
    return enriched


def add_display_species(
    data: dict | None,
    *,
    language: str | None = None,
    settings: dict | None = None,
) -> dict | None:
    """Return a copy with displaySpecies attached."""
    if not data:
        return data

    localized = get_localized_common_name_from_english(
        data.get('species'),
        language=language,
        settings=settings,
    )

    enriched = dict(data)
    enriched['displaySpecies'] = localized
    return enriched
