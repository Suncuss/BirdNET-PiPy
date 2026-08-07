"""Unit tests for media capability signing (auth/privacy redesign Phase 2).

The media secret normally comes from auth.json; these patch the in-memory cache
directly so the tests don't touch the filesystem.
"""
import threading
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

    def test_reset_cannot_be_overtaken_by_an_inflight_cache_fill(self):
        """A reset after rotation must be the last cache mutation.

        Previously, a cold fill could read the old key, pause while a password
        change reset the cache, then publish that old key after the reset.
        """
        from core import media_access

        fill_started = threading.Event()
        release_fill = threading.Event()
        reset_done = threading.Event()
        errors = []

        def read_old_secret():
            fill_started.set()
            if not release_fill.wait(timeout=2):
                raise TimeoutError('cache reset did not reach the forced race')
            return 'old-secret'

        def fill_cache():
            try:
                media_access._media_secret()
            except Exception as exc:  # surfaced in the main test thread
                errors.append(exc)

        def reset_cache():
            try:
                media_access.reset_secret_cache()
            except Exception as exc:  # surfaced in the main test thread
                errors.append(exc)
            finally:
                reset_done.set()

        media_access.reset_secret_cache()
        with patch.object(media_access, 'get_or_create_media_secret',
                          side_effect=read_old_secret):
            fill_thread = threading.Thread(target=fill_cache)
            fill_thread.start()
            assert fill_started.wait(timeout=2)

            reset_thread = threading.Thread(target=reset_cache)
            reset_thread.start()
            assert not reset_done.wait(timeout=0.1)

            release_fill.set()
            fill_thread.join(timeout=2)
            reset_thread.join(timeout=2)

        assert not fill_thread.is_alive()
        assert not reset_thread.is_alive()
        assert not errors
        assert media_access._cached_secret is None

        with patch.object(media_access, 'get_or_create_media_secret',
                          return_value='new-secret'):
            assert media_access._media_secret() == 'new-secret'
        media_access.reset_secret_cache()
