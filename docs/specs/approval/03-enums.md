# Approval 모듈 세부 설계 - Enum 정의

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# Enum 정의

### ApprovalStatus (StrEnum)

| 값 | 설명 | 상세 |
|----|------|------|
| `PENDING` | 대기 | 요청이 생성되어 사용자 판단을 기다리는 상태. 알림이 발송된다 |
| `APPROVED` | 승인 | 사용자가 승인하여 executor가 성공적으로 실행된 상태 |
| `EXECUTION_FAILED` | 실행 실패 | 승인 후 executor 실행이 실패한 상태. 원인 해소 후 재승인(`approve`), 거절(`reject`), 보류(`hold`), 철회(`cancel`) 가능 |
| `REJECTED` | 거절 | 사용자가 거절한 상태. `reject_reason`에 사유가 기록된다. 요청자가 `reopen()`으로 params/body를 수정하여 재상신할 수 있다 |
| `ON_HOLD` | 보류 | 사용자가 판단을 유보한 상태. `resume()`으로 PENDING으로 되돌릴 수 있다 |
| `EXPIRED` | 만료 | `expires_at` 시각이 경과하여 자동 만료된 상태. Agent는 필요 시 새 요청을 생성한다 |
| `CANCELLED` | 철회 | 요청자(Agent)가 사용자 처리 전에 스스로 철회한 상태. PENDING 또는 ON_HOLD에서만 전환 가능 |

### ApprovalType (StrEnum)

| 값 | 설명 | 승인 시 실행 내용 |
|----|------|------------------|
| `STRATEGY_ADOPT` | 전략 채택 | `ReportStore.update_status(report_id, "adopted")` + `StrategyRegistry.update_status(strategy_id, "adopted")` → 전략이 ADOPTED 상태로 전환되어 봇에 배정 가능해진다. 전결 대상에서 제외된다 |
| `STRATEGY_RETIRE` | 전략 폐기 | `ReportStore.update_status(report_id, "retired")` + `StrategyRegistry.update_status(strategy_id, "archived")` → 전략이 ARCHIVED 상태로 전환된다. 봇은 전략 복제본을 사용하므로 운영 중인 봇에는 영향 없음. 전결 대상에서 제외된다 |
| `BOT_CREATE` | 봇 신규 생성 | `BotManager.create_bot(**params)` → 전략을 실행하는 새 봇이 생성되고, Treasury에서 예산이 할당된다 |
| `BOT_ASSIGN_STRATEGY` | 봇에 전략 배정 | `BotManager.assign_strategy(bot_id, strategy_id)` → 봇에 채택된 전략을 배정한다. 봇이 running 상태이면 즉시 새 전략으로 전환된다 |
| `BOT_CHANGE_STRATEGY` | 봇 전략 변경 | `BotManager.change_strategy(bot_id, strategy_id)` → 중지 상태의 봇에 다른 전략을 교체 배정한다. 봇이 running 상태이면 거부된다 |
| `BOT_STOP` | 봇 중지 | `BotManager.stop_bot(bot_id)` → 봇의 전략 루프가 중지되고, 미체결 주문이 취소된다. 보유 포지션은 유지된다 |
| `BOT_RESUME` | 봇 재개 | `BotManager.resume_bot(bot_id)` → 중지 또는 에러 상태의 봇을 재시작한다. Agent가 재개 사유(에러 해소, 시장 안정화 등)를 판단하여 요청한다 |
| `BOT_DELETE` | 봇 삭제 | `BotManager.delete_bot(bot_id)` → 중지 상태의 봇을 완전히 제거한다. 보유 포지션이 있으면 거부된다. 할당 예산은 Treasury 미할당으로 반환된다 |
| `BUDGET_CHANGE` | 봇 예산 변경 | `Treasury.update_budget(bot_id, amount)` → 해당 봇의 할당 예산이 변경되고, 미할당 잔액이 재계산된다 |
| `RULE_CHANGE` | 전략별 규칙 변경 | `RuleEngine.update_rules(bot_id, rules)` → 해당 봇의 거래 규칙(최대 포지션 비율, 손절선 등)이 즉시 갱신된다 |
