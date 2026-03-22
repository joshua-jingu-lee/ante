"""credentials Fernet 암호화 단위 테스트."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from ante.account.crypto import decrypt_credentials, encrypt_credentials


class TestEncryptDecryptRoundtrip:
    """암호화/복호화 라운드트립 테스트."""

    def test_roundtrip_simple(self):
        """간단한 credentials dict가 암호화 후 복호화하면 원본과 동일하다."""
        original = {"app_key": "my-key", "app_secret": "my-secret"}
        encrypted = encrypt_credentials(original)
        decrypted = decrypt_credentials(encrypted)
        assert decrypted == original

    def test_roundtrip_empty(self):
        """빈 dict도 암호화/복호화가 정상 동작한다."""
        original: dict = {}
        encrypted = encrypt_credentials(original)
        decrypted = decrypt_credentials(encrypted)
        assert decrypted == original

    def test_roundtrip_nested(self):
        """중첩 dict도 암호화/복호화가 정상 동작한다."""
        original = {
            "app_key": "key123",
            "app_secret": "secret456",
            "extra": {"nested": True, "count": 42},
        }
        encrypted = encrypt_credentials(original)
        decrypted = decrypt_credentials(encrypted)
        assert decrypted == original


class TestEncryptOutput:
    """암호화 출력 검증."""

    def test_encrypt_returns_different_from_plaintext(self):
        """암호화 결과가 평문 JSON과 다르다."""
        original = {"app_key": "my-key", "app_secret": "my-secret"}
        encrypted = encrypt_credentials(original)
        assert encrypted != '{"app_key": "my-key", "app_secret": "my-secret"}'

    def test_encrypt_returns_string(self):
        """암호화 결과가 문자열이다."""
        encrypted = encrypt_credentials({"key": "value"})
        assert isinstance(encrypted, str)

    def test_decrypt_returns_dict(self):
        """복호화 결과가 dict이다."""
        encrypted = encrypt_credentials({"key": "value"})
        decrypted = decrypt_credentials(encrypted)
        assert isinstance(decrypted, dict)


class TestMissingKey:
    """환경변수 미설정 시 에러 검증."""

    def test_encrypt_missing_key_raises(self, monkeypatch):
        """ANTE_DB_ENCRYPTION_KEY 미설정 시 RuntimeError."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ANTE_DB_ENCRYPTION_KEY"):
            encrypt_credentials({"key": "value"})

    def test_decrypt_missing_key_raises(self, monkeypatch):
        """ANTE_DB_ENCRYPTION_KEY 미설정 시 RuntimeError."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ANTE_DB_ENCRYPTION_KEY"):
            decrypt_credentials("some-encrypted-string")


class TestWrongKey:
    """다른 키로 복호화 시 에러 검증."""

    def test_wrong_key_raises(self, monkeypatch):
        """암호화 시 사용한 키와 다른 키로 복호화하면 InvalidToken."""
        original = {"app_key": "my-key"}
        encrypted = encrypt_credentials(original)

        # 다른 키로 변경
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", new_key)

        with pytest.raises(InvalidToken):
            decrypt_credentials(encrypted)


class TestEmptyKey:
    """빈 키 처리."""

    def test_empty_key_raises(self, monkeypatch):
        """빈 문자열 키는 RuntimeError."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "")
        with pytest.raises(RuntimeError, match="ANTE_DB_ENCRYPTION_KEY"):
            encrypt_credentials({"key": "value"})
