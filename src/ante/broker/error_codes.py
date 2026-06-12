"""KIS API 에러코드 분류.

KIS rt_cd / msg_cd 기반으로 재시도 가능 여부를 판별한다.

KIS msg_cd는 ``APBK*`` 형식 또는 numeric business code(예: ``40580000``)
모두 가능하다. 두 형식 모두 동일하게 ``PERMANENT_MSG_CODES`` /
``TRANSIENT_MSG_CODES`` set에 등록한다.
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
        "40580000",  # 장종료 또는 주문불가 시간 (#1296: A7 oracle 회귀)
        "40570000",  # 장시작전 (#1317: A7 oracle 회귀)
        "40240000",  # 모의투자 잔고내역 없음 = 매도가능 잔고 없음 (#1951: #1945 회귀)
        # 모의투자 주문이 불가한 계좌 = 계좌 자격/모의 신청 상태 거절
        # (#2361: 3세션 일관 관측, 조사 #2360)
        "40910000",
        "IGW00022",  # 원주문번호 오류 또는 처리 불가 (#1338: A7 oracle 회귀)
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
    "40580000": "장종료 또는 주문불가 시간",
    "40570000": "장시작전",
    "40240000": "모의투자 잔고내역 없음 (매도가능 잔고 없음)",
    "40910000": "모의투자 주문 불가 계좌 (모의 자격/신청 상태 확인 필요)",
    "IGW00022": "원주문번호 오류 또는 처리 불가",
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


# ── 예수금 부족 관련 에러 코드 ────────────────────────────
INSUFFICIENT_DEPOSIT_CODE = "APBK0919"  # 잔고(예수금) 부족


def is_insufficient_deposit(msg_cd: str) -> bool:
    """예수금 부족 에러인지 판별."""
    return msg_cd == INSUFFICIENT_DEPOSIT_CODE


def get_error_message(msg_cd: str, fallback: str = "") -> str:
    """KIS msg_cd에 대한 한글 에러 메시지 반환."""
    return KIS_ERROR_MESSAGES.get(msg_cd, fallback or f"알 수 없는 에러 ({msg_cd})")
