"""KIS error code 분류: ``IGW00022`` permanent 등록 검증 (#1338).

`IGW00022`는 KIS 주문취소/정정 응답에서 "원주문번호 오류 또는 처리 불가"를
의미하는 broker business error로, 재시도해도 동일 결과가 반복되는
permanent 코드다. ``PERMANENT_MSG_CODES``와 ``KIS_ERROR_MESSAGES``에
모두 등록되어 있어야 한다.
"""

from __future__ import annotations

from ante.broker.error_codes import (
    KIS_ERROR_MESSAGES,
    PERMANENT_MSG_CODES,
    is_retryable_msg_code,
)


def test_is_retryable_msg_code_igw00022_is_permanent() -> None:
    """IGW00022는 permanent로 분류되어 재시도 불가."""
    assert is_retryable_msg_code("IGW00022") is False


def test_kis_error_messages_igw00022_present() -> None:
    """IGW00022는 한글 메시지 매핑에 등록되어 있다."""
    assert "IGW00022" in KIS_ERROR_MESSAGES
    assert KIS_ERROR_MESSAGES["IGW00022"]


def test_igw00022_in_permanent_msg_codes() -> None:
    """IGW00022는 PERMANENT_MSG_CODES set에 포함된다."""
    assert "IGW00022" in PERMANENT_MSG_CODES
