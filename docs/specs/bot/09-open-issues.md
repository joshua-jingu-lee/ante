# Bot 모듈 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 미결 사항

- [x] 알림 메시지 발행 — `bot/manager.py`에서 NotificationEvent 직접 발행 구현 완료 (category: "bot")
- [ ] 텔레그램 `/bots` 응답 메시지 스펙 적용 ([#529](https://github.com/joshua-jingu-lee/ante/issues/529)) — 헤더에 실행 중 봇 수 표시, 상태값 한글화 (`running` → `실행 중` 등). 에픽: [#531](https://github.com/joshua-jingu-lee/ante/issues/531)
- [ ] 텔레그램 `/stop` 응답 메시지 스펙 적용 ([#530](https://github.com/joshua-jingu-lee/ante/issues/530)) — 보유 종목 유무에 따른 메시지 분기, 이미 중지됨 분기 추가, 상태값 한글 표시. 에픽: [#531](https://github.com/joshua-jingu-lee/ante/issues/531)
- [ ] `BotManager.stop_bot()`에 `suppress_notification` 파라미터 추가 ([#518](https://github.com/joshua-jingu-lee/ante/issues/518)) — `True`이면 `_suppress_notification_bot_ids` set 기반으로 `_on_bot_stopped()` 경로에서 NotificationEvent 발행 생략. 에픽: [#515](https://github.com/joshua-jingu-lee/ante/issues/515)

**`/bots` 응답 메시지 예시:**

```
🤖 봇 목록 (2/3 실행 중)
  bot-001 [실행 중] momentum_breakout
  bot-002 [실행 중] mean_reversion
  bot-003 [중지됨] pair_trading
```

**`/stop` 응답 메시지 — 결과 분기:**

| 조건 | 응답 |
|------|------|
| 보유 종목 없음 | 아래 메시지 A |
| 보유 종목 있음 | 아래 메시지 B |
| 봇 미존재 | `봇을 찾을 수 없습니다: {bot_id}` |
| 이미 중지됨 | `이미 중지된 봇입니다: {bot_id}` |

**메시지 A — 보유 종목 없음:**

```
ℹ️ *봇 중지*

봇: {봇이름} ({bot_id})
상태: 실행 중 → 중지됨

미체결 주문은 자동 취소되지 않습니다.
```

**메시지 B — 보유 종목 있음:**

```
ℹ️ *봇 중지*

봇: {봇이름} ({bot_id})
상태: 실행 중 → 중지됨

⚠️ 보유 종목 {N}개가 유지됩니다.
중지 후 포지션을 직접 관리해야 합니다.

보유: {종목1}, {종목2}, ...
체결대기: {금액}원
```
