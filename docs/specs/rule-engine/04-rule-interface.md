# Rule Engine 모듈 세부 설계 - 룰 인터페이스 (Rule ABC)

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 룰 인터페이스 (Rule ABC)

> 소스: `src/ante/rule/base.py`

### Rule 클래스 메서드

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `__init__` | `(self, rule_id: str, config: Dict[str, Any])` | 룰 ID와 설정으로 초기화. `name`, `description`, `priority`, `enabled` 추출 |
| `evaluate` | `(self, context: RuleContext) -> RuleEvaluation` | **(abstract)** 룰 평가 로직. 서브클래스에서 구현 필수 |
| `is_applicable` | `(self, context: RuleContext) -> bool` | 이 룰이 해당 상황에 적용되는지 확인. 기본값은 `self.enabled` 반환 |

### RuleResult (Enum)

> 소스: `src/ante/rule/base.py`

| 값 | 설명 |
|----|------|
| `PASS` | 통과 |
| `WARN` | 경고 (통과하되 로깅) |
| `BLOCK` | 차단 (거래 중지) |
| `REJECT` | 거부 (이 주문만 취소) |

### RuleAction (Enum)

> 소스: `src/ante/rule/base.py`

| 값 | 설명 |
|----|------|
| `LOG` | 로깅만 |
| `NOTIFY` | 알림 발송 |
| `STOP_BOT` | 봇 중지 |
| `HALT_ACCOUNT` | 계좌 중지 |

### RuleEvaluation (dataclass, frozen)

> 소스: `src/ante/rule/base.py`

| 필드 | 타입 | 설명 |
|------|------|------|
| `rule_id` | `str` | 룰 고유 ID |
| `rule_name` | `str` | 룰 표시 이름 |
| `result` | `RuleResult` | 평가 결과 |
| `action` | `RuleAction` | 위반 시 조치 |
| `message` | `str` | 평가 메시지 |
| `metadata` | `Dict[str, Any]` | 추가 메타데이터 |
