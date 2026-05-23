"""CLI ``_validators.py`` 모듈 단위 테스트.

본 모듈은 :mod:`ante.cli._validators`가 노출하는 공유 callback의 invariant를
직접 호출 단위로 단정한다. e2e Click runner 회귀는 별도 파일에서 호출 표면별로
검증한다 (예: ``tests/unit/test_cli_account_reserve_buffer_validation.py``,
``tests/unit/test_cli_treasury_amount_validation.py``).

오라클 A7 finding(#1723 — ``account create --market-order-reserve-buffer-rate``)에
서 ``validate_nonnegative_finite_amount``가 ``treasury.py``에 정의돼 있어 account
명령에서 직접 import 재사용이 어려웠다. 본 PR에서 SSOT를 ``_validators.py``로
이동했으며, 본 테스트는 그 이동된 SSOT의 동작 invariant를 보존한다.
"""

from __future__ import annotations

import json
import math

import click
import pytest

from ante.cli._validators import (
    reject_invalid_new_account_id,
    validate_nonnegative_finite_amount,
)
from ante.cli.formatter import OutputFormatter


class TestValidateNonnegativeFiniteAmount:
    """``validate_nonnegative_finite_amount`` callback 단위 테스트.

    Click ``callback`` 시그니처는 ``(ctx, param, value)`` 3-tuple — ctx/param은
    None을 전달해도 callback 자체 분기에는 영향이 없다 (이미 SSOT가 사용하는
    동형 ``validate_positive_finite_amount`` 패턴과 동일).
    """

    def test_inf_raises_bad_parameter(self) -> None:
        """``+Infinity``는 BadParameter (NaN/Infinity 거부)."""
        with pytest.raises(click.BadParameter) as exc_info:
            validate_nonnegative_finite_amount(None, None, math.inf)
        assert "finite" in str(exc_info.value)

    def test_nan_raises_bad_parameter(self) -> None:
        """``NaN``은 BadParameter (NaN/Infinity 거부)."""
        with pytest.raises(click.BadParameter) as exc_info:
            validate_nonnegative_finite_amount(None, None, math.nan)
        assert "finite" in str(exc_info.value)

    def test_negative_raises_bad_parameter(self) -> None:
        """음수는 BadParameter (0 이상이어야 함)."""
        with pytest.raises(click.BadParameter) as exc_info:
            validate_nonnegative_finite_amount(None, None, -0.1)
        assert "0 이상" in str(exc_info.value)

    def test_zero_passes(self) -> None:
        """0은 boundary 정상값 (``Decimal('0')`` 기본값 SSOT, #1333)."""
        assert validate_nonnegative_finite_amount(None, None, 0.0) == 0.0

    def test_positive_passes(self) -> None:
        """양수는 정상 통과."""
        assert validate_nonnegative_finite_amount(None, None, 0.005) == 0.005

    def test_none_passes_through(self) -> None:
        """``None``(옵션 미지정)은 그대로 ``None`` 반환 (분기 보존)."""
        assert validate_nonnegative_finite_amount(None, None, None) is None


class TestRejectInvalidNewAccountId:
    """``reject_invalid_new_account_id`` helper 단위 테스트 (#1724).

    create-path 신규 account_id를 ``AccountService.create`` SQL 진입 이전에
    `VALIDATION_ERROR` + `SystemExit(1)`로 거부하는지 단정한다. 동형 sibling
    ``reject_invalid_account_id``와 달리 RESTRICTED-aware
    (``validate_new_account_id`` 위임 — ``test`` 같은 bootstrap seed id도 거부).
    """

    def test_restricted_default_id_raises_system_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``default``는 RESTRICTED → SystemExit(1), code=VALIDATION_ERROR."""
        fmt = OutputFormatter(fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            reject_invalid_new_account_id("default", fmt, context="cli.account.create")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        envelope = json.loads(captured.out.strip().splitlines()[-1])
        assert envelope["status"] == "error"
        assert envelope["code"] == "VALIDATION_ERROR"

    def test_pattern_violation_raises_system_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``bad_id`` (underscore — 패턴 위반) → SystemExit(1), VALIDATION_ERROR."""
        fmt = OutputFormatter(fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            reject_invalid_new_account_id("bad_id", fmt, context="cli.account.create")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        envelope = json.loads(captured.out.strip().splitlines()[-1])
        assert envelope["code"] == "VALIDATION_ERROR"

    def test_empty_string_raises_system_exit(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``""``는 형식 위반 → SystemExit(1), VALIDATION_ERROR."""
        fmt = OutputFormatter(fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            reject_invalid_new_account_id("", fmt, context="cli.account.create")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        envelope = json.loads(captured.out.strip().splitlines()[-1])
        assert envelope["code"] == "VALIDATION_ERROR"

    def test_none_raises_system_exit(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``None``은 형식 위반 → SystemExit(1), VALIDATION_ERROR.

        ``reject_invalid_account_id``(lookup-policy)와 달리 create-path는
        ``None``도 정상 입력으로 받지 않는다 (``validate_new_account_id``
        계약).
        """
        fmt = OutputFormatter(fmt="json")
        with pytest.raises(SystemExit) as exc_info:
            reject_invalid_new_account_id(None, fmt, context="cli.account.create")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        envelope = json.loads(captured.out.strip().splitlines()[-1])
        assert envelope["code"] == "VALIDATION_ERROR"

    def test_valid_account_id_returns_value(self) -> None:
        """valid한 account_id는 그대로 반환 (정상 통과)."""
        fmt = OutputFormatter(fmt="json")
        result = reject_invalid_new_account_id(
            "valid-acc-1", fmt, context="cli.account.create"
        )
        assert result == "valid-acc-1"
