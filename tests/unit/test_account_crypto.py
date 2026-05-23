"""credentials Fernet 암호화 단위 테스트."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from ante.account.crypto import (
    EncryptionKeyError,
    EncryptionKeyInvalidError,
    EncryptionKeyMissingError,
    decrypt_credentials,
    encrypt_credentials,
)


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
    """환경변수 미설정 시 에러 검증.

    ``EncryptionKeyMissingError`` 가 raise되고, behavior preserving을 위해
    ``RuntimeError`` 서브클래스이며 안정 ``code`` 속성을 갖는다.
    """

    def test_encrypt_missing_key_raises_typed(self, monkeypatch):
        """ANTE_DB_ENCRYPTION_KEY 미설정 시 EncryptionKeyMissingError."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        with pytest.raises(EncryptionKeyMissingError) as excinfo:
            encrypt_credentials({"key": "value"})
        assert isinstance(excinfo.value, RuntimeError)  # behavior preserving
        assert isinstance(excinfo.value, EncryptionKeyError)
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_MISSING"
        assert "ANTE_DB_ENCRYPTION_KEY" in str(excinfo.value)

    def test_decrypt_missing_key_raises_typed(self, monkeypatch):
        """ANTE_DB_ENCRYPTION_KEY 미설정 시 EncryptionKeyMissingError."""
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        with pytest.raises(EncryptionKeyMissingError) as excinfo:
            decrypt_credentials("some-encrypted-string")
        assert isinstance(excinfo.value, RuntimeError)
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_MISSING"

    def test_empty_key_raises_typed(self, monkeypatch):
        """빈 문자열 키도 EncryptionKeyMissingError."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "")
        with pytest.raises(EncryptionKeyMissingError) as excinfo:
            encrypt_credentials({"key": "value"})
        assert isinstance(excinfo.value, RuntimeError)
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_MISSING"


class TestInvalidKeyFormat:
    """Fernet 형식 위반 키는 EncryptionKeyInvalidError."""

    def test_garbage_value_raises_invalid(self, monkeypatch):
        """알 수 없는 garbage 문자열은 형식 위반으로 INVALID."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "not-valid-base64")
        with pytest.raises(EncryptionKeyInvalidError) as excinfo:
            encrypt_credentials({"key": "value"})
        assert isinstance(excinfo.value, RuntimeError)
        assert isinstance(excinfo.value, EncryptionKeyError)
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_INVALID"
        assert "ANTE_DB_ENCRYPTION_KEY" in str(excinfo.value)

    def test_wrong_length_raises_invalid(self, monkeypatch):
        """길이가 44가 아닌 값은 INVALID (44는 Fernet canonical key 길이)."""
        # 길이 43 (44 - 1)이지만 ``=``로 끝나는 값.
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "A" * 42 + "==")
        with pytest.raises(EncryptionKeyInvalidError) as excinfo:
            encrypt_credentials({"key": "value"})
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_INVALID"

    def test_decrypt_invalid_format_raises_invalid(self, monkeypatch):
        """decrypt 경로에서도 형식 위반은 INVALID."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "not-valid-base64")
        with pytest.raises(EncryptionKeyInvalidError):
            decrypt_credentials("some-encrypted-string")


class TestWrongKeyDecrypt:
    """valid 형식이지만 다른 키로 복호화 시 EncryptionKeyInvalidError."""

    def test_wrong_key_raises_invalid_chained(self, monkeypatch):
        """암호화 시 사용한 키와 다른 valid Fernet 키로 복호화하면
        EncryptionKeyInvalidError가 InvalidToken을 체이닝해 raise된다."""
        original = {"app_key": "my-key"}
        encrypted = encrypt_credentials(original)

        # 다른 valid key로 변경.
        new_key = Fernet.generate_key().decode()
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", new_key)

        with pytest.raises(EncryptionKeyInvalidError) as excinfo:
            decrypt_credentials(encrypted)
        assert isinstance(excinfo.value, RuntimeError)
        assert isinstance(excinfo.value, EncryptionKeyError)
        assert excinfo.value.code == "DB_ENCRYPTION_KEY_INVALID"
        # 원본 InvalidToken은 __cause__로 보존된다.
        assert isinstance(excinfo.value.__cause__, InvalidToken)
