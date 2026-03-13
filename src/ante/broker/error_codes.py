"""KIS API 에러코드 분류.

KIS rt_cd / msg_cd 기반으로 재시도 가능 여부를 판별한다.
"""

# ── 재시도 불가 (permanent) KIS msg_cd ─────────────────
# 잘못된 요청, 비즈니스 에러 등 재시도해도 결과가 동일한 에러
PERMANENT_MSG_CODES: frozenset[str] = frozenset(
    {
        "APBK0013",  # 잘못된 종목코드
        "APBK0014",  # 매매 불가 종목
        "APBK0919",  # 잔고 부족
        "APBK0920",  # 매도 가능 수량 초과
        "APBK0921",  # 주문 수량 제한 초과
        "APBK1000",  # 호가 범위 초과
        "APBK1001",  # 최소 주문 금액 미달
        "APBK1002",  # 시장 마감
        "APBK1003",  # 주문 불가 시간
        "APBK0501",  # 잘못된 계좌번호
        "APBK0502",  # 잘못된 비밀번호
        "APBK0503",  # 잘못된 주문 유형
    }
)

# ── 재시도 가능 (transient) KIS msg_cd ──────────────────
# 서버 과부하, 일시적 지연 등 재시도 시 성공할 수 있는 에러
TRANSIENT_MSG_CODES: frozenset[str] = frozenset(
    {
        "APBK0600",  # 서버 과부하
        "APBK0601",  # 처리 지연
        "APBK0602",  # 일시적 서비스 불가
    }
)

# ── 재시도 가능 HTTP 상태 코드 ──────────────────────────
RETRYABLE_HTTP_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 429})

# ── KIS 에러 한글 메시지 매핑 ──────────────────────────
KIS_ERROR_MESSAGES: dict[str, str] = {
    "APBK0013": "잘못된 종목코드",
    "APBK0014": "매매 불가 종목",
    "APBK0919": "잔고 부족",
    "APBK0920": "매도 가능 수량 초과",
    "APBK0921": "주문 수량 제한 초과",
    "APBK1000": "호가 범위 초과",
    "APBK1001": "최소 주문 금액 미달",
    "APBK1002": "시장 마감",
    "APBK1003": "주문 불가 시간",
    "APBK0501": "잘못된 계좌번호",
    "APBK0502": "잘못된 비밀번호",
    "APBK0503": "잘못된 주문 유형",
    "APBK0600": "서버 과부하 (재시도 가능)",
    "APBK0601": "처리 지연 (재시도 가능)",
    "APBK0602": "일시적 서비스 불가 (재시도 가능)",
}


def is_retryable_msg_code(msg_cd: str) -> bool:
    """KIS msg_cd가 재시도 가능한지 판별."""
    if msg_cd in PERMANENT_MSG_CODES:
        return False
    if msg_cd in TRANSIENT_MSG_CODES:
        return True
    # 알 수 없는 코드는 재시도 가능으로 취급 (보수적)
    return True


def is_retryable_http_status(status_code: int) -> bool:
    """HTTP 상태 코드가 재시도 가능한지 판별."""
    return status_code in RETRYABLE_HTTP_STATUS_CODES


def get_error_message(msg_cd: str, fallback: str = "") -> str:
    """KIS msg_cd에 대한 한글 에러 메시지 반환."""
    return KIS_ERROR_MESSAGES.get(msg_cd, fallback or f"알 수 없는 에러 ({msg_cd})")
