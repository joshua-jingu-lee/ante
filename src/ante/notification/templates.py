"""알림 메시지 템플릿 상수.

모든 알림 메시지의 서식과 텍스트를 한곳에서 관리한다.
각 상수는 str.format() 호환 포맷 문자열이다.
"""

# ── CRITICAL ──────────────────────────────────

TRADING_STATE_CHANGED = (
    "🚨 *거래 상태 변경*\n{old_state} → *{new_state}*\n사유: {reason}"
)

POSITION_MISMATCH = (
    "🚨 *포지션 불일치*\n"
    "봇: `{bot_id}` · 종목: `{symbol}`\n"
    "내부: {internal_qty:.0f}주 · 브로커: {broker_qty:.0f}주\n"
    "사유: {reason}"
)

# ── ERROR ─────────────────────────────────────

BOT_ERROR = "❌ *봇 에러*\n봇: `{bot_id}`\n{error_message}"

RESTART_EXHAUSTED = (
    "❌ *봇 재시작 한도 소진*\n봇: `{bot_id}` · {restart_attempts}회 시도\n{last_error}"
)

ORDER_CANCEL_FAILED = (
    "❌ *주문 취소 실패*\n봇: `{bot_id}` · 주문: `{order_id}`\n{error_message}"
)

CIRCUIT_BREAKER = (
    "❌ *Circuit Breaker*\n브로커: `{broker}`\n{old_state} → *{new_state}* ({reason})"
)

# ── INFO ──────────────────────────────────────

ORDER_FILLED = (
    "📈 *체결 완료*\n"
    "봇: `{bot_id}`\n"
    "종목: *{display}*\n"
    "{side} {quantity}주 @ {price:,.0f}원"
)
