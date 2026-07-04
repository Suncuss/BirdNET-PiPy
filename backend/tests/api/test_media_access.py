"""Unit tests for media capability signing (auth/privacy redesign Phase 2).

The media secret normally comes from auth.json; these patch the in-memory cache
directly so the tests don't touch the filesystem.
"""
import time
from unittest.mock import patch


def _parse(query):
    return dict(part.split('=', 1) for part in query.split('&'))


class TestMediaSigning:
    def test_sign_then_verify_roundtrip(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            parts = _parse(media_access.sign_media_query('clip.mp3'))
            assert media_access.verify_media_signature(
                'clip.mp3', parts['exp'], parts['sig'],
            ) is True

    def test_rejects_other_filename(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            parts = _parse(media_access.sign_media_query('clip.mp3'))
            # A signature for clip.mp3 must not authorize a different file.
            assert media_access.verify_media_signature(
                'other.mp3', parts['exp'], parts['sig'],
            ) is False

    def test_rejects_tampered_signature(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            parts = _parse(media_access.sign_media_query('clip.mp3'))
            assert media_access.verify_media_signature(
                'clip.mp3', parts['exp'], 'deadbeef',
            ) is False

    def test_rejects_expired(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            past = int(time.time()) - 10
            sig = media_access._compute_sig('clip.mp3', past)
            assert media_access.verify_media_signature('clip.mp3', str(past), sig) is False

    def test_rejects_after_secret_rotation(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            parts = _parse(media_access.sign_media_query('clip.mp3'))
        with patch.object(media_access, '_cached_secret', 'secret-b'):
            assert media_access.verify_media_signature(
                'clip.mp3', parts['exp'], parts['sig'],
            ) is False

    def test_rejects_missing_or_malformed(self):
        from core import media_access
        with patch.object(media_access, '_cached_secret', 'secret-a'):
            assert media_access.verify_media_signature('clip.mp3', None, None) is False
            assert media_access.verify_media_signature('clip.mp3', '', '') is False
            assert media_access.verify_media_signature('clip.mp3', 'notanint', 'x') is False
            # A non-ASCII sig must deny cleanly (no TypeError -> 500).
            future = str(int(time.time()) + 1000)
            assert media_access.verify_media_signature('clip.mp3', future, 'ünïcödé') is False
