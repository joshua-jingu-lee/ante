# Approval 모듈 세부 설계 - 결재 유형

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 결재 유형

| type | 설명 | params 예시 | 승인 시 실행 내용 | executor 상태 |
|------|------|-------------|------------------|--------------|
| `strategy_adopt` | 전략 채택 | `{"strategy_name": "...", "strategy_id": "...", "report_id": "..."}` | `ReportStore.update_status(report_id, "adopted")` + `StrategyRegistry.update_status(strategy_id, "adopted")` 호출 → 전략이 ADOPTED 상태로 전환되어 봇에 배정 가능해진다 | 등록됨 |
| `strategy_retire` | 전략 폐기 | `{"strategy_name": "...", "strategy_id": "...", "report_id": "...", "reason": "성과 부진"}` | `ReportStore.update_status(report_id, "retired")` + `StrategyRegistry.update_status(strategy_id, "archived")` 호출 → 전략이 ARCHIVED 상태로 전환된다. 봇은 전략 복제본을 사용하므로 운영 중인 봇에는 영향 없음 | 등록됨 |
| `bot_create` | 봇 신규 생성 | `{"config": {"bot_id": "...", "strategy_id": "...", "name": "...", "account_id": "domestic-demo", "interval_seconds": 60}}` | `params.config`를 `BotConfig`로 변환하고 `StrategyRegistry`에서 ADOPTED 전략을 조회한 뒤 `StrategyLoader.load(record.filepath)`와 `BotManager.create_bot(config=..., strategy_cls=..., source_path=...)`를 호출한다. 예산 배정은 별도 `budget_change` 요청으로 처리한다 | 등록됨 |
| `bot_assign_strategy` | 봇에 전략 배정 | `{"bot_id": "...", "strategy_id": "..."}` | `BotManager.assign_strategy(bot_id, strategy_id)` 호출 → 봇에 채택된 전략을 배정한다. running 상태이면 즉시 새 전략으로 전환된다 | 등록됨 |
| `bot_change_strategy` | 봇 전략 변경 | `{"bot_id": "...", "strategy_id": "..."}` | `BotManager.change_strategy(bot_id, strategy_id)` 호출 → 중지 상태의 봇에 다른 전략을 교체 배정한다. running 상태이면 거부된다 | 등록됨 |
| `bot_stop` | 봇 중지 | `{"bot_id": "...", "reason": "손실 누적"}` | `BotManager.stop_bot(bot_id)` 호출 → 봇의 전략 루프가 중지되고, 미체결 주문이 취소된다. 보유 포지션은 유지된다 | 등록됨 |
| `bot_resume` | 봇 재개 | `{"bot_id": "...", "reason": "에러 해소 확인"}` | `BotManager.resume_bot(bot_id)` 호출 → 중지 또는 에러 상태의 봇을 재시작한다. Agent가 재개 사유를 판단하여 요청한다 | 등록됨 |
| `bot_delete` | 봇 삭제 | `{"bot_id": "...", "reason": "전략 폐기"}` | `BotManager.delete_bot(bot_id)` 호출 → 중지 상태의 봇을 완전히 제거한다. 보유 포지션이 있으면 거부된다. 할당 예산은 Treasury 미할당으로 반환된다 | 등록됨 |
| `budget_change` | 봇 예산 변경 | `{"bot_id": "...", "amount": 25000000, "current": 10000000}` | `Treasury.update_budget(bot_id, amount)` 호출 → 해당 봇의 할당 예산이 변경되고, 미할당 잔액이 재계산된다 | 등록됨 |
| `rule_change` | 전략별 규칙 변경 | `{"bot_id": "...", "rules": {"max_position_pct": 0.2}}` | `RuleEngine.update_rules(bot_id, rules)` 호출 → 해당 봇의 거래 규칙(최대 포지션 비율, 손절선 등)이 즉시 갱신된다 | 등록됨 |

결재 유형은 열린 구조로, 새로운 유형을 추가할 때 `type` 문자열과 실행 핸들러만 등록하면 된다.

> **구현 현황**: 10개 결재 유형 모두 main.py에 executor가 등록되어 있다. `bot_create` executor payload는 `params.config`의 `BotConfig` 필드만 사용하며, `mode`, `budget`, `strategy_cls`를 params에 저장하지 않는다.
