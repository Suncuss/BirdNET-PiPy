"""Tests for the shared internal secret that gates /api/broadcast/*.

The secret file path + cache are redirected to a tmp dir by the autouse
``isolate_internal_secret`` fixture in tests/conftest.py, so each test starts
with a fresh, isolated secret and nothing is written to the live data dir.
"""


class TestInternalSecret:
    """get_or_create_internal_secret / verify_internal_secret behavior."""

    def test_generates_and_persists_with_strict_perms(self, tmp_path):
        from core import internal_auth

        secret = internal_auth.get_or_create_internal_secret()
        assert secret
        assert len(secret) >= 32

        path = tmp_path / 'internal_secret'
        assert path.exists()
        mode = path.stat().st_mode & 0o777
        assert mode & 0o600 == 0o600  # owner can read/write
        assert mode & 0o077 == 0      # group/other have no access

    def test_stable_across_calls(self):
        from core import internal_auth

        first = internal_auth.get_or_create_internal_secret()
        second = internal_auth.get_or_create_internal_secret()
        assert first == second

    def test_reads_preexisting_file(self, tmp_path):
        # Simulate the other process (api/main) having created it first.
        (tmp_path / 'internal_secret').write_text('preexisting-secret')

        from core import internal_auth
        assert internal_auth.get_or_create_internal_secret() == 'preexisting-secret'

    def test_verify_matches_only_correct_secret(self):
        from core import internal_auth

        secret = internal_auth.get_or_create_internal_secret()
        assert internal_auth.verify_internal_secret(secret) is True
        assert internal_auth.verify_internal_secret('wrong') is False
        assert internal_auth.verify_internal_secret('') is False
        assert internal_auth.verify_internal_secret(None) is False
