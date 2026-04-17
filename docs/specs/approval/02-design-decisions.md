# Approval 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 설계 결정

### Report와의 관계

Report는 전략 검증의 근거 자료(백테스트 결과, 분석 내용)이며, Approval은 그 근거를 바탕으로 한 의사결정 행위다. 전략 채택 결재(`strategy_adopt`)는 Report를 참조할 수 있지만, Report 자체가 결재는 아니다.

```
Agent: 리포트 제출 (근거 자료)
  → 결재 요청 생성 (strategy_adopt, report_id 참조)
    → 사용자 승인
      → 전략 채택 상태로 전환
```

### 만료 정책

결재 요청에는 만료 기한을 설정할 수 있다. 시장 상황이 변할 수 있으므로, 오래된 요청이 뒤늦게 승인되는 것을 방지한다. 만료된 요청은 자동으로 `expired` 상태로 전환되며, Agent는 필요 시 새 요청을 생성한다.

### 외부 메신저를 통한 결재 처리

사용자가 외출 중이거나 Dashboard에 접근할 수 없을 때, Telegram 등 외부 메신저에서 바로 결재를 처리할 수 있어야 한다.

**흐름:**
1. 결재 요청 생성 시, Notification이 Telegram으로 요약 메시지를 전송한다.
2. 메시지에는 인라인 버튼(승인/거절) 또는 응답 명령어(`/approve <id>`, `/reject <id>`)가 포함된다.
3. 사용자가 응답하면 Notification 어댑터가 이를 수신하여 `ApprovalService.approve()` 또는 `reject()`를 호출한다.

**Notification 어댑터 현황:**

Notification 모듈은 양방향 통신을 지원한다. `TelegramAdapter`가 발송을, `TelegramCommandReceiver`가 getUpdates 폴링 기반 명령 수신을 담당한다.

- **발송**: `ApprovalCreatedEvent` 구독 → 결재 요약 메시지 + 인라인 버튼(승인/거절) 전송
- **수신**: 인라인 버튼 `callback_query` 또는 `/approve <id>`, `/reject <id>` 명령어 → `ApprovalService` 호출

**인라인 버튼 결재 흐름:**

```
결재 요청 생성
  → NotificationService가 ApprovalCreatedEvent 수신
    → TelegramAdapter.send_with_buttons():
      메시지: "📋 결재 요청 [budget_change]\n전략 A 예산 증액\n..."
      버튼:  [✅ 승인] [❌ 거절]
                ↓ callback_data: "approve:{id}" / "reject:{id}"

사용자가 버튼 탭
  → TelegramCommandReceiver가 callback_query 수신
    → ApprovalService.approve(id) 또는 reject(id)
    → 처리 결과 메시지 응답
```

인라인 버튼으로 거절 시 기본 사유("사용자 거절")를 사용한다. 상세 사유가 필요하면 `/reject <id> <reason>` 명령어를 직접 입력한다.

**보안**: `TELEGRAM_CHAT_ID`와 일치하는 사용자만 명령을 실행할 수 있다. 개인 홈서버 환경에서는 이 수준이면 충분하다.

상세 설계: [notification.md — 결재 인라인 버튼](../notification/notification.md#결재-인라인-버튼)

### 사전 검증과 참조자

결재 요청은 사용자에게 도달하기 전에 관련 모듈이나 역할 Agent의 사전 검증을 거칠 수 있다. 이는 현실 회사에서 실무 부서가 품의서를 검토한 후 대표에게 올리는 것과 같다.

**시스템 모듈 자동 검증:**
- 요청 생성 시 유형에 따라 관련 모듈이 자동으로 검증을 수행한다.
- 예: `budget_change` → Treasury가 가용 잔액 확인, RuleEngine이 규칙 위반 여부 확인

**외부 Agent 검토:**
- 특정 역할을 맡은 Agent(자금팀장, 리스크 분석 등)가 `ante approval review` 커맨드로 검토 의견을 첨부한다.
- 이 Agent는 전략 개발 Agent와 별개의 역할로, 자체 판단 기준에 따라 의견을 남긴다.

**검증은 조언이지 거부권이 아니다:**
- `result: "fail"`인 검증이 있더라도 사용자는 승인할 수 있다. 최종 결정은 항상 사용자에게 있다.
- 단, `fail` 검증이 포함된 요청은 알림 메시지에 경고를 표시한다.

### 결재 철회

Agent가 결재 요청을 생성한 후, 사용자가 처리하기 전에 **스스로 철회**할 수 있다. 시장 상황이 변하거나 전략을 재검토해야 할 때 불필요한 결재가 사용자의 판단 대기열에 남지 않도록 한다.

- `pending` 또는 `on_hold` 상태에서만 철회 가능하다.
- 이미 처리된(`approved`, `rejected`, `expired`) 요청은 철회할 수 없다.
- 철회 시 요청자만 철회할 수 있다 (본인이 올린 결재만 회수).

### 감사 이력

결재 요청의 모든 상태 변경은 `history`에 시간순으로 기록된다. 누가 언제 무엇을 했는지 추적할 수 있어, 의사결정 과정을 사후에 검토할 수 있다.

```python
# history entry 구조
{
    "action": str,    # created | review_added | held | resumed | approved | rejected | cancelled | expired
    "actor": str,     # 행위자 (예: "agent:strategy-dev", "user", "treasury", "system")
    "at": str,        # 시각
    "detail": str,    # 부가 정보 (거절 사유, 보류 사유 등)
}
```

모든 상태 변경 메서드(`create`, `add_review`, `approve`, `reject`, `hold`, `resume`, `cancel`, `expire_stale`)가 자동으로 history entry를 추가한다.

### 전결 (자동 승인)

> ⚠️ 이 기능은 Agent의 요청을 사용자 확인 없이 즉시 실행한다. 잘못된 설정은 의도하지 않은 거래·자금 변동으로 이어질 수 있으므로 신중하게 사용해야 한다.

특정 조건을 만족하는 결재 요청을 사용자 승인 없이 자동으로 처리하는 기능이다. `system.toml`의 `[approval.auto_approve]` 섹션으로 관리한다. 기본값은 모두 비활성화이다.

**설정 구조:**

```toml
[approval.auto_approve]
enabled = false                  # 전결 기능 전체 on/off (기본: false)

# 유형별 전결 규칙 (enabled = true일 때만 적용)
[approval.auto_approve.rules]
bot_stop = true                  # 봇 중지는 항상 자동 승인
bot_create_paper = true          # 모의투자 봇 생성은 자동 승인
budget_change_max = 5000000      # 예산 변경 500만원 이하 자동 승인 (0이면 비활성)
```

**규칙 평가 흐름:**

```
ApprovalService.create()
  → auto_approve.enabled == true?
    → 유형별 규칙 매칭:
      - bot_stop: 항상 자동 승인
      - bot_create: params.mode == "paper"이면 자동 승인
      - budget_change: params.amount <= budget_change_max이면 자동 승인
    → 매칭 시: status를 APPROVED로 설정, executor 즉시 실행
      - history에 actor: "system:auto_approve" 기록
      - 알림 발송 시 "[자동 승인]" 접두사 표시
    → 미매칭 시: 일반 PENDING 흐름
```

**안전 장치:**

- `enabled = false`가 기본값이므로 명시적으로 켜야만 동작한다.
- `strategy_adopt`는 전결 대상에 포함하지 않는다 — 전략 채택은 항상 사용자 판단이 필요하다.
- 자동 승인된 요청도 감사 이력에 `"actor": "system:auto_approve"`로 기록되어 추적 가능하다.
- 자동 승인 시에도 알림은 발송된다 (사후 인지 보장).

### 사용자 직접 실행과의 구분

사용자가 Dashboard에서 직접 수행하는 작업(예산 변경, 봇 생성 등)은 Approval을 거치지 않는다. Approval은 오직 Agent → 사용자 방향의 요청에만 적용된다.
