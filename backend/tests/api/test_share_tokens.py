"""Unit tests for stateless detection share tokens (Phase 3).

The serializer is built per call from auth.json's share_secret; these patch that
secret directly (no filesystem/app needed). Rotating it invalidates tokens.
"""
from unittest.mock import patch


def _secret(value='unit-secret'):
    from core import share_tokens
    return patch.object(share_tokens, 'get_or_create_share_secret', return_value=value)


class TestShareTokens:
    def test_roundtrip_binds_to_one_id(self):
        from core import share_tokens
        with _secret():
            token = share_tokens.mint_share_token(42)
            assert share_tokens.verify_share_token(token, 42) is True
            assert share_tokens.share_token_subject(token) == 42

    def test_rejects_other_id(self):
        from core import share_tokens
        with _secret():
            token = share_tokens.mint_share_token(42)
            # The signed sub means a mutated URL id is rejected.
            assert share_tokens.verify_share_token(token, 43) is False

    def test_rejects_garbage_and_none(self):
        from core import share_tokens
        with _secret():
            assert share_tokens.verify_share_token('not-a-token', 42) is False
            assert share_tokens.verify_share_token(None, 42) is False
            assert share_tokens.share_token_subject('not-a-token') is None

    def test_rejects_after_secret_rotation(self):
        from core import share_tokens
        with _secret('secret-a'):
            token = share_tokens.mint_share_token(42)
        # Rotating the share secret invalidates every outstanding link.
        with _secret('secret-b'):
            assert share_tokens.verify_share_token(token, 42) is False

    def test_rejects_expired(self):
        from core import share_tokens
        with _secret():
            token = share_tokens.mint_share_token(42)
            with patch.object(share_tokens, 'SHARE_TOKEN_TTL_SECONDS', -1):
                assert share_tokens.verify_share_token(token, 42) is False
