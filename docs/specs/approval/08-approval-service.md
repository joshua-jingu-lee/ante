# Approval 모듈 세부 설계 - ApprovalService

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# ApprovalService

**생성자 파라미터:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `db` | Database | SQLite 연결 인스턴스 |
| `eventbus` | EventBus | 이벤트 발행용 |
| `executors` | dict[str, Callable] | 유형별 승인 시 실행 핸들러 |
| `validators` | dict[str, Callable] | 유형별 사전 검증 핸들러. `fail` 시 요청 생성 차단, `warn` 시 reviews에 경고 첨부 |

**메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마 생성 |
| `create` | type, requester, title, body, params, reference_id, expires_at | ApprovalRequest | 요청 생성 + ApprovalCreatedEvent 발행 |
| `add_review` | id, reviewer, result, detail | ApprovalRequest | 검토 의견 추가 (시스템 모듈 또는 외부 Agent) |
| `approve` | id, resolved_by | ApprovalRequest | 승인 처리 + 자동 실행 |
| `reject` | id, resolved_by, reject_reason | ApprovalRequest | 거절 처리 |
| `cancel` | id, requester | ApprovalRequest | 요청자 철회 (pending/on_hold → cancelled). 본인 요청만 철회 가능 |
| `hold` | id | ApprovalRequest | 보류 전환 |
| `resume` | id | ApprovalRequest | 보류 해제 → pending |
| `reopen` | id, requester, body, params | ApprovalRequest | 거절된 요청을 수정하여 재상신 (rejected → pending). body와 params를 갱신할 수 있다. 본인 요청만 reopen 가능. 사전 검증(validator)을 재실행한다 |
| `get` | id | ApprovalRequest \| None | 단건 조회 |
| `list` | status, type, search, limit, offset | list[ApprovalRequest] | 필터 조회. `search`: title/requester LIKE 키워드 검색 |
| `expire_stale` | — | int | 만료 기한이 지난 요청 일괄 expired 처리. 처리 건수 반환 |

### 만료 스케줄러

`expire_stale()`은 **주기적 스케줄러**로 호출한다. `main.py`의 `asyncio` 이벤트 루프에서 5분 간격 태스크로 등록한다.

```python
# main.py 초기화 시
async def _expire_loop(approval_service: ApprovalService, interval: float = 300.0):
    while True:
        await asyncio.sleep(interval)
        expired = await approval_service.expire_stale()
        if expired:
            logger.info("결재 만료 처리: %d건", expired)

asyncio.create_task(_expire_loop(approval_service))
```

만료 처리 시 건별로 `ApprovalResolvedEvent(status=expired)`가 발행되어 사용자에게 알림이 전달된다.

### 자동 실행 (Executor)

`approve()` 호출 시 `executors[request.type]`을 호출하여 즉시 실행한다. Executor는 시스템 초기화 시 등록된다.

```python
# main.py 초기화 예시
executors = {
    "strategy_adopt": lambda params: report_store.adopt(params["report_id"]),
    "budget_change": lambda params: treasury.update_budget(params["bot_id"], params["amount"]),
    "bot_create": lambda params: bot_manager.create_bot(**params),
    "bot_stop": lambda params: bot_manager.stop_bot(params["bot_id"]),
    "rule_change": lambda params: rule_engine.update_rules(params["bot_id"], params["rules"]),
}
```

### Executor 이중 검증

결재 요청의 유효성은 **생성 시(사전)**와 **실행 시(사후)** 두 단계에서 검증된다.
요청 생성과 승인 사이에 시스템 상태가 변할 수 있으므로, 양쪽 모두에서 검증이 필수적이다.

**1단계 — 사전 검증 (요청 생성 시)**

`create()` 호출 시 유형별로 등록된 `validators`가 현 시점의 상태를 검증한다.
검증 결과는 `fail` 또는 `warn` 등급으로 구분되며, `reviews`에 첨부된다.

| 등급 | 동작 | 성격 |
|------|------|------|
| `fail` | **요청 생성 차단** — 예외를 발생시켜 요청이 만들어지지 않는다 | 논리적으로 실행 불가능한 상태. 해소 없이는 승인해도 executor가 반드시 거부한다 |
| `warn` | 요청은 생성되되 경고가 reviews에 첨부된다 | 판단 여지가 있는 상태. 사용자가 상황을 보고 승인 여부를 결정할 수 있다 |

`fail`로 차단함으로써 Agent가 선행 조건을 먼저 해소(봇 전략 변경, 포지션 청산 등)한 뒤 재시도하도록 유도한다.

| 유형 | 검증 내용 | 등급 | 검증 주체 |
|------|----------|------|----------|
| `strategy_retire` | 전략이 이미 ARCHIVED 상태인가 | `fail` | StrategyRegistry |
| `bot_create` | 전략이 adopted 상태인가 | `fail` | ReportStore |
| `bot_create` | 동일 이름의 봇이 이미 존재하는가 | `fail` | BotManager |
| `bot_delete` | 보유 포지션이 있는가 | `fail` | Trade |
| `bot_delete` | 봇이 stopped 상태인가 | `fail` | BotManager |
| `bot_change_strategy` | 봇이 stopped 상태인가 | `fail` | BotManager |
| `bot_assign_strategy` | 전략이 adopted 상태인가 | `fail` | ReportStore |
| `bot_resume` | 봇이 stopped 또는 error 상태인가 | `fail` | BotManager |
| `budget_change` | Treasury 미할당 잔액이 증액분을 감당할 수 있는가 | `warn` | Treasury |

```python
# ApprovalService.create() 내부 흐름
validator = self._validators.get(request_type)
if validator:
    result = validator(params)          # ValidationResult(grade, detail)
    if result.grade == "fail":
        raise ApprovalValidationError(result.detail)
    elif result.grade == "warn":
        reviews.append({"reviewer": result.reviewer, "result": "warn", "detail": result.detail})
```

**2단계 — 실행 시 검증 (승인 후 executor 내부)**

`approve()` → executor 호출 시, executor는 **현 시점의 사전조건(precondition)**을 다시 검증한다.
사전 검증을 통과했더라도 승인 대기 중 상태가 변할 수 있으므로 이 검증은 필수적이다.
조건 불충족 시 executor가 예외를 발생시키며, 실행 실패로 기록된다.

| 유형 | 실행 시 사전조건 | 실패 시 |
|------|-----------------|--------|
| `strategy_retire` | 전략이 REGISTERED 또는 ADOPTED 상태 | 거부 — 이미 ARCHIVED 상태 |
| `budget_change` | Treasury 미할당 잔액 ≥ 증액분 | 거부 — 자금 부족 |
| `bot_create` | 전략이 adopted 상태, 동일 봇 미존재 | 거부 — 전략 미채택 또는 봇 중복 |
| `bot_delete` | 봇이 stopped 상태, 보유 포지션 없음 | 거부 — 봇 중지 및 포지션 청산 필요 |
| `bot_change_strategy` | 봇이 stopped 상태 | 거부 — running 중에는 전략 변경 불가 |
| `bot_resume` | 봇이 stopped 또는 error 상태 | 거부 — 이미 running 상태 |
| `bot_assign_strategy` | 전략이 adopted 상태 | 거부 — 전략 미채택 |
| `rule_change` | 봇이 존재하고 running 또는 stopped 상태 | 거부 — 봇 미존재 |

**실행 결과 기록**: executor 성공 시 `APPROVED` 상태를 유지하고, 실패 시 `EXECUTION_FAILED`로 전환한다. 결과와 에러 메시지는 감사 이력(`history`)에 기록된다.

```python
# executor 실행 흐름 (ApprovalService.approve 내부)
request.status = "approved"
self._append_history(request, "approved", actor)
try:
    executor = self._executors[request.type]
    executor(request.params)                     # 내부에서 precondition 검증
    self._append_history(request, "executed", actor)
except Exception as e:
    request.status = "execution_failed"
    self._append_history(request, "execution_failed", actor, detail=str(e))
```

`execution_failed` 상태에서는 원인 해소 후 다음 전환이 가능하다:
- `approve()` → 재승인하여 executor 재실행
- `reject()` → 거절 처리
- `hold()` → 보류 전환
- `cancel()` → 철회
