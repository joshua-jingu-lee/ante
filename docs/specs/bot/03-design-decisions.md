# Bot 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 설계 결정

### 봇 상태 머신

BotStatus는 다음 6가지 상태를 갖는 StrEnum이다: `CREATED`, `RUNNING`, `STOPPING`, `STOPPED`, `ERROR`, `DELETED`.

**상태 전이**:
```
CREATED → RUNNING → STOPPING → STOPPED → DELETED
                  ↘ ERROR           ↗
```

**RUNNING 이탈과 잠금을 기다리던 작업**: 봇이 RUNNING을 떠나면(정지, ERROR, 삭제, 계좌 정지) `_signal_lock`을 기다리던 외부 시그널은 잠금을 얻은 뒤 버려지고 `on_data`가 불리지 않는다. 시그널이 봇의 핸들러(`on_external_signal`)에 들어온 뒤 봇이 다시 시작됐으면(재개, `assign_strategy`, 자동 재시작) 상태가 RUNNING이어도 버려진다. `start()`는 봇을 RUNNING으로 바꿀 때마다 세대 번호를 올린다. 외부 시그널은 봇의 핸들러에 들어올 때, 실행 루프는 시작할 때의 세대를 적어 둔다. 이전 세대의 실행 루프는 간격 대기에서 깨어나거나 잠금을 얻었을 때 스텝을 실행하지 않고 끝난다. 이렇게 끝날 때와 이전 세대의 루프가 예외로 끝날 때에는 봇의 상태와 실행 태스크를 바꾸지 않고 이벤트도 발행하지 않는다(예외는 경고 로그로만 남긴다). 옛 실행 루프에 대한 이 서술은 루프가 끝나는 지점만 다룬다.

**정지 뒤의 주문**: `stop()`이 불리면, 그리고 실행 루프가 예외나 연속 시간 초과로 봇을 ERROR로 바꾸면 그 봇의 주문이 닫힌다. 주문은 다음 `start()`에서만 다시 열린다. 주문이 닫힌 뒤에는 `on_step`과 `on_data`가 돌려준 시그널을 `OrderRequestEvent`로 발행하지 않는다. 시그널마다 발행 직전에 확인하므로, 실행 중이던 콜백이 돌려준 시그널과 같은 목록에서 아직 발행되지 않은 시그널이 모두 버려진다. 콜백이 시작된 뒤 봇이 다시 시작됐으면(세대 번호가 다르면) 새 세대에서 주문이 열려 있어도 그 콜백의 시그널은 버려진다. 버린 건수는 경고 로그로만 남는다. 실행 루프가 한 스텝의 시그널을 발행한 뒤 세대가 바뀌었으면, 그 옛 루프는 대기 액션을 발행하지 않고 `BotStepCompletedEvent`도 내지 않고 끝난다. 실행 루프가 예외로 끝날 때 봇의 정지가 이미 끝났으면(STOPPED·DELETED) 상태를 ERROR로 바꾸지 않고 `BotErrorEvent`와 실패의 `BotStepCompletedEvent`도 발행하지 않는다(예외는 경고 로그로만 남긴다). 그래서 정지된 봇이 이 경로로 자동 재시작되지 않는다. 다음은 이 규칙의 대상이 아니다: 체결 통보로 불린 `on_fill`의 후속 주문, 남은 스탑 주문의 트리거가 내는 주문 요청(ERROR 전이 뒤의 스탑 주문과, 아래 정리가 끝난 뒤 `on_fill` 후속으로 등록된 스탑 주문), 청산을 동반한 삭제의 청산 주문, 취소·정정 액션, 주문이 닫히기 전에 이미 발행된 `OrderRequestEvent`.

**정지 때의 미체결 주문 (#3049)**: `BotManager`가 `BotStoppedEvent`를 받아 그 봇의 활성 스탑 주문을 만료시키고 미체결 주문에 취소를 요청한다. 그래서 정리는 봇이 STOPPED가 된 뒤에 일어난다. 정지 종류별 처리는 다음과 같다.

| 정지 종류 | 미체결 주문 | 스탑 주문 |
|---|---|---|
| `stop_bot`(수동 `ante bot stop`, 텔레그램 `/stop`, 결재 `bot_stop`, 규칙의 `BotStopEvent`). RUNNING·ERROR 모두 | 취소 | 만료 |
| 실행 중인 봇의 `assign_strategy` | 취소한 뒤 재시작 | 만료 |
| `delete_bot` | 취소. 실행 중이면 정지 때, CREATED·STOPPED·ERROR면 삭제가 직접 한다. 청산 주문보다 먼저 | 만료 |
| 실행 루프의 자기 정지(연속 시그널 초과) | 취소 | 만료 |
| 계좌 정지(그 계좌의 봇과 어느 봇에도 없는 주문, 삭제 중 제외) | 백그라운드 취소(아래 「계좌 정지」) | 즉시 만료(`account_suspended`) |
| 서버 종료(`stop_all`) | 취소하지 않는다 | 그보다 먼저 `StopOrderManager.stop()`이 `manager_stopped`로 만료시킨다 |
| ERROR 전이 | 취소하지 않는다(자동 재시작이 이어받는다) | 만료하지 않는다 |

- 대상은 정리를 시작할 때 주문 추적기의 DB에서 그 봇의 `open`·`partially_filled` 주문이다. 주문마다 `OrderCancelEvent(reason="bot_stopped")`(계좌 정지는 `"account_suspended"`)를 발행해 게이트웨이의 취소 경로를 탄다. 부분 체결 주문은 잔량만 취소된다. 가상 계좌의 주문은 추적 기록이 없어 스탑 주문만 대상이다. 승인과 제출 사이에 있던 주문도 추적 기록이 없어 빠진다(알려진 한계).
- 스탑 주문은 첫 await 전에 모두 만료로 표시되어 그 뒤의 시세에 발동하지 않고, 주문마다 `StopOrderExpiredEvent(reason="bot_stopped")`(계좌 정지는 `"account_suspended"`)를 한 번 낸다.
- 취소 요청이 돌아온 뒤 추적기의 상태가 `cancelled`면 취소, 아니면 실패로 센다. 실패(브로커가 `False`를 돌려주거나 예외를 낸 경우)는 정지를 실패시키지 않는다. 그 주문은 열린 채 남고 체결은 폴링이 반영한다. 취소한 주문에 취소 접수 전의 체결이 있으면 늦은 체결로 반영된다([broker-adapter/18-fill-recovery.md](../broker-adapter/18-fill-recovery.md) §6.3).
- 정지 명령은 취소 요청과 브로커의 응답까지 마친 뒤 돌아온다. 체결 확인은 기다리지 않는다. 계좌 정지는 예외다(아래 「계좌 정지」).
- 순서: 전략의 대기 액션(아직 발행되지 않은 취소·정정) 폐기 → 스탑 주문 만료 → 미체결 주문의 조회·취소 → 시그널 채널 닫기 → 「봇 중지」 알림. 정리가 예외로 끝나도 채널 닫기는 한다. 알림은 취소한 주문 수·취소에 실패한 주문 수·만료한 스탑 주문을 적고, 열린 주문의 조회가 실패했으면 그 사실(직접 확인 필요)을 적는다. 텔레그램 `/stop`은 알림 대신 같은 내용을 응답에 적는다. 계좌 정지로 멈춘 봇의 「봇 중지」 알림은 `중지 완료`만 적는다.
- 정지 때의 정리(`BotStoppedEvent`)를 시작할 때 봇이 STOPPED가 아니면(그 사이 다시 시작됐으면) 액션 폐기·취소·만료를 건너뛰고 경고 로그만 남긴다. 정리 도중(만료·조회·취소 요청 하나마다의 뒤) 봇의 상태나 세대 번호가 바뀌었으면 정리는 거기서 멈추고, 남은 주문은 취소되지 않는다(알려진 한계). ERROR 전이는 `BotStoppedEvent`를 내지 않으므로 대기 액션도 그대로 둔다.
- 한 주문에 취소 요청은 동시에 하나다. `BotManager`의 정리(봇 정지·삭제·계좌 정지)는 취소를 낼 때 같은 진행 중 집합을 지나고, 그 집합은 발행부터 결과 조회까지를 덮는다. 다른 정리가 취소 중인 주문은 건너뛰고 「취소하지 않고 남긴 열린 주문: N건 (다른 정리가 취소 중이거나 실행·삭제 중인 봇)」으로 적는다(수동 정지에는 그 경합에서만 나온다). 취소를 내기 직전에 추적기를 다시 읽어 열린 주문(`open`·`partially_filled`)이 아니면 내지 않는다. 실패한 취소를 다른 정리가 다시 내는 것은 재시도다.
- **계좌 정지**: `AccountSuspendedEvent`를 받으면 그 계좌의 봇마다 예약된 자동 재시작을 취소하고, 실행 중이면 멈춘다. 이렇게 멈춘 봇의 정리는 대기 액션 폐기와 스탑 주문 만료만 한다. 실행 중이 아니고 삭제 중이 아닌 봇(ERROR·STOPPED·CREATED, 정지가 예외로 끝난 봇)도 대기 액션을 버리고 스탑 주문을 만료한다. 그 뒤 브로커를 기다리지 않고 돌아온다. 한 봇의 처리가 예외로 끝나도 다음 봇과 아래 정리는 계속된다.
- 계좌 정지의 열린 주문 취소는 계좌마다 하나인 백그라운드 정리가 한다. 정리는 그 계좌의 열린 주문을 추적기 DB에서 읽고, 주문의 봇이 실행 중이거나 삭제 중이면 건너뛰고, 나머지(어느 봇에도 없는 주문 포함)에 취소를 낸다. 끝나면 계좌당 한 건 `NotificationEvent(title="계좌 정지 — 주문 정리 결과", category="system")`를 낸다. 본문은 계좌 ID와 위의 정리 결과 줄(만료한 스탑 주문 포함)이고, 실패·조회 실패·건너뜀이 있으면 `warning`, 아니면 `info`다. 모두 0이고 조회 실패도 없으면 내지 않는다.
- 정리가 도는 중에 같은 계좌의 정지가 다시 오면(상태 쓰기가 실패한 정지를 다시 보낸 경우) 새 정리를 띄우지 않고 지금의 정리가 끝난 뒤 한 번 더 돈다. 여러 번 겹쳐도 한 번이다. 정리가 예상 밖 예외로 끝나면 예외 로그와 critical 알림 「계좌 정지 — 주문 정리 실패, 직접 확인 필요」 한 건을 낸다. 서버 종료(`stop_all`)는 진행 중인 정리를 취소하고 기다린다. 결과 알림과 킬 스위치 알림(「거래 상태 변경 (킬 스위치)」)의 순서는 보장하지 않는다(알려진 한계).

**근거**:
- NautilusTrader는 INITIALIZED/RUNNING/STOPPED/DEGRADED/FAULTING/DISPOSED 6단계
- Ante는 6단계 — DELETED 상태를 추가하여 삭제된 봇의 상태를 명시적으로 구분
- STOPPING 상태로 graceful shutdown 지원. 정지할 때 열린 주문의 정리는 STOPPED가 된 뒤에 한다(위 「정지 때의 미체결 주문」)

### BotConfig

> 소스: `src/ante/bot/config.py`

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `bot_id` | `str` | (필수) | 고유 ID |
| `strategy_id` | `str` | (필수) | 등록된 전략 ID (또는 파일 경로) |
| `account_id` | `str` | (필수) | 소속 계좌 ID. **생성 후 불변** — `update_bot`으로 변경할 수 없다(아래 `update_bot` 항목 참조) |
| `name` | `str` | `""` | 봇 표시 이름 |
| `interval_seconds` | `int` | `60` | `on_step()` 호출 주기 (초) |
| `auto_restart` | `bool` | `True` | 에러 시 자동 재시작 여부 |
| `max_restart_attempts` | `int` | `3` | 최대 재시작 시도 횟수 |
| `restart_cooldown_seconds` | `int` | `60` | 재시작 쿨다운 (초) |
| `step_timeout_seconds` | `int` | `30` | `on_step()` 호출 타임아웃 (초). 초과 시 경고 로그 기록 |
| `max_signals_per_step` | `int` | `50` | 한 스텝에서 허용하는 최대 시그널 수. 초과 시 전체 거부 + BotErrorEvent 발행. 연속 `max_consecutive_failures`회 초과 시 봇 중지 |

**제거된 필드**:
- `bot_type`: Bot은 trading_mode를 직접 알지 못한다. Account의 `trading_mode`(LIVE/VIRTUAL)에 따라 ContextFactory가 실행 경로를 결정한다.
- `exchange`: Account의 속성이다. 봇이 독립적으로 exchange를 가지면 Account와 불일치할 수 있으므로 제거. 필요 시 `AccountService.get(account_id).exchange`로 조회한다.
- `virtual_initial_balance`: 가상 자금은 Account 레벨에서 관리한다.

**실행 간격 제한**: `interval_seconds`는 `MIN_INTERVAL_SECONDS`(10초) 이상 `MAX_INTERVAL_SECONDS`(3600초) 이하여야 한다. 범위 밖이면 `ValueError` 발생. `validate_interval()` 함수로 검증.

### Bot 클래스

> 소스: `src/ante/bot/bot.py`

**퍼블릭 메서드**:

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `start` | — | `None` | 봇 시작. 전략 인스턴스화 + 실행 루프 Task 생성 |
| `stop` | — | `None` | 봇 중지. 실행 루프 취소 + 전략 정리 |
| `on_order_filled` | `event: object` | `None` | 체결 통보를 전략에 전달. `OrderFilledEvent`만 처리하고 자기 bot_id만 필터링. 후속 Signal(손절/익절)을 즉시 발행 |
| `on_order_update` | `event: object` | `None` | 주문 상태 변경 통보를 전략의 `on_order_update()`에 전달. `OrderSubmittedEvent`, `OrderRejectedEvent`, `OrderCancelledEvent`, `OrderFailedEvent`, `OrderCancelFailedEvent` 처리 |
| `on_external_signal` | `event: object` | `None` | 외부 시그널 채널에서 수신한 데이터를 전략의 `on_data()`에 전달. `accepts_external_signals=True`인 전략만 처리 |
| `get_info` | — | `dict[str, Any]` | 봇 상태 정보(bot_id, account_id, trading_mode, exchange, currency, status, config 등) 반환 |

**설계 근거**:

1. **Bot은 구체 클래스 (ABC 아닌)**
   - 이전 초안은 Bot을 ABC로 정의하고 LiveBot/VirtualBot이 상속
   - 실제로 실행 루프는 동일 — 차이는 StrategyContext에 주입되는 DataProvider와 PortfolioView
   - LIVE/VIRTUAL 차이는 Bot이 아니라 ContextFactory가 Account의 trading_mode를 참조하여 결정

2. **Signal → OrderRequestEvent 변환은 Bot의 책임**
   - 전략은 Signal만 반환 (시스템 이벤트를 모름)
   - Bot이 Signal을 EventBus 이벤트로 변환하여 발행
   - 이로써 전략 코드가 EventBus에 의존하지 않음

3. **OrderAction → EventBus 이벤트 변환 (`_publish_actions`)**
   - `_run_loop()`에서 매 스텝 후 `StrategyContext._drain_actions()`로 주문 취소/정정 액션을 수집
   - `action == "cancel"` → `OrderCancelEvent`, `action == "modify"` → `OrderModifyEvent`로 변환하여 발행
   - **modify v1=price-only (#2391)**: Bot은 `OrderModifyEvent`를 발행만 하며(`action.quantity or 0.0`로 수량을 접음 — `0.0`=price-only 미지정), broker-level 정정 v1은 `open` 주문의 가격 정정(수량 불변)을 지원한다. 룰/Gateway fail-closed 통과 시 `OrderModifyExecutedEvent` → Bot이 `on_order_update` status=`modified`로 전략에 통보한다. 고급 케이스(수량변경 등)는 fail-closed 거부되므로 그 경우 `cancel` 후 재주문으로 대체한다(후속 #2393).

4. **체결 통보 전달 (`on_order_filled`)**
   - Bot이 EventBus에서 OrderFilledEvent를 구독
   - 자기 bot_id인 이벤트만 필터링하여 전략의 `on_fill()`에 전달
   - 전략은 dict로만 받으므로 EventBus 이벤트 타입에 의존하지 않음

5. **주기적 루프 (interval_seconds)**
   - 타임프레임별 호출 주기는 봇 설정으로 관리
   - 1분봉 전략: 60초, 5분봉: 300초, 일봉: 장 마감 후 1회
   - 전략은 호출 주기를 모르고, 호출될 때마다 판단만 수행

### BotManager

> 소스: `src/ante/bot/manager.py`

**퍼블릭 메서드**:

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `create_bot` | `config: BotConfig, strategy_cls: type[Strategy], ctx: StrategyContext \| None = None` | `Bot` | 봇 생성. ctx가 주입되면 그대로 사용하고, None이면 context_factory로 자동 생성. 이벤트 구독 등록 + DB 저장. `accepts_external_signals=True`이면 시그널 키 자동 발급. `bot_id`가 메모리에 있거나 `deleted` 행으로 남아 있으면 `BotAlreadyExistsError`(`BOT_ALREADY_EXISTS`) — 삭제한 id는 다시 쓸 수 없다(보유·이력 귀속) |
| `start_bot` | `bot_id: str` | `None` | 봇 시작. `bot.start()` 호출 |
| `stop_bot` | `bot_id: str` | `StopCleanup \| None` | 봇 중지. 스탑 주문을 만료시키고 미체결 주문을 취소한 결과(취소 건수·실패 건수·만료한 스탑 주문·조회 실패 여부)를 돌려준다. 정리를 건너뛰었으면 `None`(위 「정지 때의 미체결 주문」) |
| `update_bot` | `bot_id: str, updates: dict` | `Bot` | 봇 설정 수정. **중지 상태에서만 가능** — RUNNING이면 `BotError` 발생. BotConfig는 frozen dataclass이므로 재생성 패턴 적용: 기존 config를 dict로 풀고 → updates 병합 → 새 BotConfig 생성 → Bot.config 교체 → DB 갱신. `budget` 키가 포함되면 `Treasury.deallocate()` + `Treasury.allocate()`로 예산 재조정. `strategy_id` 변경 시 StrategyRegistry 존재 확인 + exchange 호환성 검증 후 실행 코드도 함께 교체(아래 「전략 교체」). **`account_id`는 불변 필드** — updates에 현재 값과 다른 `account_id`가 포함되면 `BotImmutableFieldError`(안정 코드 `BOT_IMMUTABLE_FIELD`, validation 카테고리) 발생. 같은 값(no-op)·미포함은 통과 |

**`account_id` 불변 정책 (#2282)**: 봇의 `account_id`는 생성 후 변경할 수 없다. treasury 예산은 옛 account 아래에 할당되고, broker credential도 옛 account에 바인딩되며, 포지션 격리도 account-bound이므로, `account_id`를 변경하면 이 자원들이 새 account로 재배치되지 않아 불일치가 발생한다. 단일 사용자 홈서버에서 복잡한 re-isolation(예산 이전·credential 재바인딩·포지션 마이그레이션)을 구현하는 대신, `account_id`를 `update_bot`의 불변 필드로 제약한다(YAGNI 안전 기본). 변경이 필요하면 봇을 삭제한 뒤 **새 `bot_id`로** 다시 만든다. 이는 Account의 불변 필드(`exchange`/`currency`/`trading_mode`/`broker_type`, `AccountImmutableFieldError`) 정책과 정합한다([account/04-account-service.md](../account/04-account-service.md) 참조). `_save_bot_config`의 UPSERT가 `account_id` 컬럼을 갱신하는 것(#2274, create/load 경로 persistence 일관성)은 그대로 유지되며, 제약은 `update_bot` ingress에서만 적용된다.
| `delete_bot` | `bot_id: str, handle_positions: str = "keep"` | `None` | 봇 삭제. 실행 중이면 먼저 중지. CREATED·STOPPED·ERROR면 스탑 주문을 만료시키고 남은 미체결 주문을 취소한다(청산보다 먼저). `handle_positions="liquidate"` 시 TradeService를 통해 보유 종목 시장가 매도 주문 발행 후 삭제 진행. `"keep"`(기본)은 포지션 유지한 채 봇만 삭제. 이벤트 구독 해제 + VIRTUAL 계좌 봇의 VirtualExecutor 해제 + 시그널 키 폐기 + DB 레코드 삭제. `remove_bot`은 동일 기능의 별칭(alias) |
| `stop_all` | — | `None` | 모든 실행 중 봇 중지 + 재시작 태스크 취소. 미체결 주문을 취소하지 않는다. 시스템 셧다운 시 호출 |
| `list_bots` | — | `list[dict[str, Any]]` | 봇 목록 조회 |
| `get_bot` | `bot_id: str` | `Bot \| None` | 봇 조회. 없으면 None |
| `rotate_signal_key` | `bot_id: str` | `str` | 기존 시그널 키 폐기 + 새 키 발급. DB rotate 커밋 직후 해당 봇의 활성 시그널 채널을 teardown한다 — **커밋 후 NEW signal은 admit되지 않으며, 옛 키로 이미 진입한 in-flight signal은 최대 1개까지 정상 완료**(in-flight abort 아님). enforcement 메커니즘은 아래 `### 채널 teardown enforcement (#2334)` 참조. 구현 PR 머지 후 적용(동기 버그 #2333 unblock) |
| `get_signal_key` | `bot_id: str` | `str \| None` | 봇의 시그널 키 조회. `accepts_external_signals=False`이면 `None` |
| `get_restart_count` | `bot_id: str` | `int` | 봇의 현재 재시작 시도 횟수 |
| `assign_strategy` | `bot_id: str, strategy_id: str` | `None` | 봇에 전략 배정. RUNNING이면 중지→전략 교체→재시작. STOPPED/CREATED/ERROR이면 전략 ID와 실행 코드만 교체(아래 「전략 교체」). STOPPING이면 `BotError` 발생 |
| `change_strategy` | `bot_id: str, strategy_id: str` | `None` | 중지 상태 봇의 전략 ID와 실행 코드 교체(아래 「전략 교체」). RUNNING·STOPPING이면 `BotError` 발생 |
| `resume_bot` | `bot_id: str` | `None` | STOPPED/ERROR 상태 봇 재시작. 에러 카운터 리셋 후 `start()` 호출. RUNNING이면 `BotError` 발생 |
| `load_from_db` | — | `int` | DB에서 봇 설정을 읽어 메모리에 로드. deleted 제외. 반환값은 로드된 봇 수 |
| `restore_bots` | — | `int` | 서버 부팅 때 DB의 봇을 메모리에 복원(아래 「부팅 복원」). 반환값은 복원된 봇 수 |

**부팅 복원 (#2813)**: 서버 부팅 때 `restore_bots`가 `deleted`가 아닌 봇 행을 메모리에 읽어 들인다. `load_from_db`는 테스트용(가짜 전략, DB의 상태 그대로)이라 부팅에 쓰지 않는다.
- 복원된 봇의 상태는 DB의 `status`와 관계없이 `created`다(시작하지 않은 봇 — 서버가 정지된 동안의 `running`·`stopping`은 stale이다).
- 전략은 `create_bot`과 같은 순서로 준비한다(레지스트리 조회 → 등록된 파일에서 로드 → 계좌 exchange 검증 → 스냅샷 생성 → 스냅샷에서 로드). 삭제된 계좌의 행은 건너뛰고, 정지된 계좌의 행은 복원한다.
- 한 행의 준비가 실패하면(전략 없음·로드 실패·계좌 없음·설정 손상 등) 그 행만 경고 로그를 남기고 건너뛴다. 건너뛴 행은 스냅샷·이벤트 구독·봇 목록에 흔적을 남기지 않는다. 그 밖의 예외는 부팅을 멈춘다.
- 복원은 봇을 시작하지 않고, 전략별 룰 적재·시그널 키 발급·예산 변경·`bots` 행 쓰기를 하지 않는다. `auto_start`는 읽지 않는다(자동 시작은 후속 이슈).

**전략 교체 (#2838)**: `assign_strategy`·`change_strategy`·`update_bot`(`strategy_id` 변경)은 봇 설정의 전략 ID와 봇이 실행하는 전략 클래스를 함께 바꾼다. 새 전략은 봇을 건드리기 전에 `create_bot`과 같은 순서로 준비한다 — 레지스트리 조회 → 등록된 파일에서 로드 → 계좌 exchange 호환 검증 → 스냅샷 생성 → 스냅샷에서 로드. 준비가 실패하면 봇의 상태·전략 ID·실행 코드·DB가 바뀌지 않고, 실행 중이던 봇은 옛 전략으로 계속 돈다. 중지한 뒤 DB 저장이 실패하면(`update_bot`은 예산 갱신이 실패해도) 전략 ID와 실행 코드를 옛 것으로 되돌리고 봇을 정지 상태로 둔다(옛 전략을 자동으로 다시 시작하지 않는다). 되돌리기 전에 봇이 그 사이 다시 시작됐으면 되돌리지 않고 원래 오류를 올린다. 이때 봇은 새 전략 ID와 그 실행 코드로 돌고, DB는 저장 실패면 옛 ID, 예산 갱신 실패면 새 ID로 남는다. 새 전략의 `on_start`가 실패하면 `start_bot`과 같이 예외를 올리고, 봇은 새 전략에 묶인 채 정지 상태로 남는다. 같은 봇의 포지션·가상 포트폴리오는 교체 뒤에도 그대로이며 새 전략이 `ctx`로 본다. 실행 중인 봇이면 옛 전략의 미체결 주문과 스탑 주문은 재시작 전에 정리된다(「정지 때의 미체결 주문」). `Bot.start`는 봇에 묶인 전략 ID와 `config.strategy_id`가 다르면 시작하지 않고 `BotError`를 낸다.

**정지의 `on_stop` 실패 (#2697)**: `Bot.stop`은 전략의 `on_stop`이 예외를 내도 정지를 끝낸다 — 그 예외를 로그에 기록하고, 상태를 `stopped`로 바꾸고 `BotStoppedEvent`를 발행한 뒤, 그 예외를 그대로 호출자에게 올린다. `stop_bot`과 실행 중인 봇의 `assign_strategy`는 이때도 전략별 룰을 RuleEngine에서 제거하고 같은 예외를 올린다. `assign_strategy`는 전략을 바꾸지 않고, 봇은 옛 전략에 묶인 채 정지 상태로 남는다. 계좌 정지(`AccountSuspendedEvent`)는 한 봇의 `on_stop`이 실패해도 같은 계좌의 나머지 실행 중인 봇을 계속 멈춘다. 실행 루프의 자기 정지(연속 시그널 초과)도 `stopped`로 끝나고 `BotStoppedEvent`를 낸다. 자기 정지에서는 호출자가 없으므로 `on_stop`의 예외는 로그로만 남고, 실패를 알리는 별도의 오류 이벤트는 없다(직전의 시그널 초과 오류 이벤트는 그대로 나간다). 정지 자체가 취소될 때의 처리는 이 절이 정하지 않는다.

**설계 근거**:

1. **봇 유형 차이는 StrategyContext 주입으로 해결**
   - LIVE 계좌 봇: 실제 계좌 연동 PortfolioView (Treasury + Trade 경유)
   - VIRTUAL 계좌 봇: 가상 자금 PortfolioView (Treasury(잔고) + Trade(포지션) 경유 — 실전과 같은 정본)
   - DataProvider는 동일 — VIRTUAL 계좌도 실시간 시세 데이터를 사용
   - Bot 클래스는 하나, 주입되는 의존성만 다름
   - ContextFactory가 Account의 trading_mode를 참조하여 적절한 의존성을 주입

2. **봇 생성 시 계좌 검증**
   - Account 존재 및 상태(active) 확인
   - Strategy.meta.exchange와 Account.exchange 호환성 검증
   - Account가 정지(suspended) 상태이면 `AccountSuspendedError` 발생

3. **체결 통보 구독은 BotManager가 관리**
   - Bot 생성 시 EventBus 구독 등록, 삭제 시 해제
   - Bot이 직접 EventBus를 구독/해제하지 않음 → 생명주기 관리 일원화

4. **봇 설정 영속화 (SQLite)**
   - 봇 설정을 DB에 저장하여 이력 관리
   - `auto_start` 플래그로 자동 재시작 여부 제어(설정 경로와 자동 시작은 후속 이슈 — 지금은 항상 0이고 부팅 복원이 읽지 않는다)

### 봇 유형별 차이: LIVE vs VIRTUAL (Account.trading_mode 기준)

| 측면 | LIVE 계좌 봇 | VIRTUAL 계좌 봇 |
|------|-------------|----------------|
| PortfolioView | Treasury(잔고) + Trade(포지션) 경유 | VirtualPortfolioView, Treasury(잔고) + Trade(포지션) 경유 |
| 주문 처리 | OrderRequestEvent → RuleEngine → BrokerAdapter → 실제 주문 | OrderRequestEvent → RuleEngine → VirtualExecutor → 가상 체결 |
| 데이터 | 실시간 시세 (API Gateway 경유) | 실시간 시세 (동일) |
| 자금 | Treasury에서 할당받은 실제 자금 | Treasury에서 할당받은 가상 자금(봇 예산) |
| 체결 | BrokerAdapter가 실제 체결 후 OrderFilledEvent 발행 | VirtualExecutor가 즉시 가상 체결 → FillApplier direct 적용 후 OrderFilledEvent 발행. 봇의 보유를 넘는 매도는 실패 종결(`virtual_insufficient_holdings`) |
| 브로커 접근 | `AccountService.get_broker(account_id)` | — (VirtualExecutor 사용) |
| 예산 접근 | `TreasuryManager.get(account_id)` | `TreasuryManager.get(account_id)` |

**근거**:
- Bot 자체는 trading_mode를 모른다. Account의 trading_mode에 따라 ContextFactory가 실행 경로를 결정
- Bot 코드는 동일, 주입되는 PortfolioView와 주문 실행 경로만 다름
- 전략 입장에서는 LIVE/VIRTUAL 구분 없이 동일한 StrategyContext API 사용

### SQLite 스키마

테이블 정의: [`bots`](../../architecture/generated/db-schema.md#bots) (코드의 DDL에서 생성된다).

- `bots.account_id`: 소속 계좌 ID
- `bots.config_json`: BotConfig 직렬화
- `bots.auto_start`: 시스템 시작 시 자동 재시작(후속 이슈 — 지금은 쓰는 코드가 없어 항상 0이고, 부팅 복원은 읽지 않는다)

### 봇 실행 흐름 (전체)

```
사용자: CLI에서 봇 생성 + 전략 로드 + 활성화
  ↓  (CLI: IPC를 통해 서버 프로세스에 위임 → `docs/specs/ipc/ipc.md` 참조)
BotManager.create_bot(config, strategy_cls, ctx?)
  → Account 존재 및 상태(active) 확인
  → Strategy.meta.exchange와 Account.exchange 호환성 검증
  → ctx가 None이면 context_factory로 StrategyContext 자동 생성
    (ContextFactory가 Account.trading_mode로 LIVE/VIRTUAL 분기)
  → Bot 인스턴스 생성 + 이벤트 구독 등록 (체결/주문상태/외부시그널)
  → accepts_external_signals=True이면 시그널 키 자동 발급
  → DB에 봇 설정 저장 (account_id 포함)
  ↓
BotManager.start_bot(bot_id)
  → bot.start()
    → Strategy(ctx) 인스턴스화
    → strategy.on_start() 호출
    → asyncio.Task로 _run_loop() 시작
    → BotStartedEvent 발행
  ↓
[주기적 루프]
  → step_context 구성 (timestamp, portfolio, balance)
  → strategy.on_step(step_context) 호출
  → signals: list[Signal] 반환
  → Signal → OrderRequestEvent 변환 + EventBus 발행
  → ctx._drain_actions() → OrderCancelEvent/OrderModifyEvent 발행
  → asyncio.sleep(interval_seconds)
  ↓
[체결 시]
  → OrderFilledEvent 수신
  → bot.on_order_filled() → strategy.on_fill() 호출
  ↓
[봇 중지 시]
  → bot.stop()
    → Task 취소
    → strategy.on_stop() 호출
    → BotStoppedEvent 발행
```

CLI의 `bot create/start/stop`과 `bot signal-key --rotate`는 위 흐름을 서버
프로세스 안에서 실행해야 하므로 런타임 IPC 전용이다. 직접 DB 수정으로 봇 status나
signal key를 바꾸면 `_bots`, 실행 task, EventBus 구독, 외부 signal channel이
어긋나므로 허용하지 않는다.

`ante bot start/stop/status`의 CLI/IPC 계약은 서버 BotManager 동작과 정렬된다.
CLI/IPC가 같은 BotManager 인스턴스를 통해 같은 검증·실행·이벤트·감사 경로를
사용해야 모든 호출자가 같은 봇에 대해 같은 결과를 얻고 같은 audit trail을 남긴다.
`start`의 계좌 프리셋 필수 인증정보 사전 검증, `BotError` → state conflict 매핑,
`bot.start`/`bot.stop` audit action 이름, `{"bot": ...}` envelope는 모두 CLI/IPC
계약에서 가져온다. cold-path fallback이나 직접 DB 수정으로 봇을 시작/중지하는
경로는 허용하지 않는다.

`bot remove`는 예외적으로 서버 실행 중에는 런타임 IPC, 서버 정지 상태에서는
cold-path cleanup을 허용한다. cold-path 삭제는 BotManager를 만들지 않고 DB에
남은 persisted state만 정리하며, 의미는 hot-path `handle_positions="keep"`과
같다. 즉 broker live 연결이 필요한 포지션 청산은 하지 않고, `signal_keys` 폐기,
`strategies/.running/{bot_id}` 스냅샷 삭제, Treasury budget 환수, `bots.status =
'deleted'` 갱신만 수행한다. DB에 `running`/`stopping` 상태가 남아 있어도 서버가
정지된 상태에서는 실행 task와 EventBus observer가 이미 부재하므로 stale status로
보고 정리한다. 다음 서버 부팅 시 BotManager는 `deleted` 봇을 로드하지 않는다.

### 외부 시그널 채널

> 참조: [strategy.md](../strategy/strategy.md) 전략 운용 방식, 외부 시그널 채널

아웃소싱/하이브리드 전략을 위해, 외부 에이전트와 봇 사이에 **CLI 파이프 기반 양방향 시그널 채널**을 제공한다.

**시그널 키 생명주기**:
```
create_bot(config)
  → 전략의 meta.accepts_external_signals 확인
    ├─ True  → signal_key 발급 + DB 저장 + 출력
    └─ False → signal_key 없음
  ↓
[운영 중]
  → rotate_signal_key(bot_id) — 키 갱신 (커밋 후 NEW signal 미admit; in-flight at-most-one 완료, abort 아님 — ↓ 채널 teardown enforcement)
  ↓
remove_bot(bot_id)
  → signal_key 폐기
```

**시그널 키 SQLite 스키마**:
테이블 정의: [`signal_keys`](../../architecture/generated/db-schema.md#signal_keys) (코드의 DDL에서 생성된다).

- `signal_keys.key_id`: "sk_" + 32자 hex (128-bit entropy)
- `signal_keys.bot_id`: 1 봇 = 1 키

**CLI 파이프 채널 동작**:

```bash
ante signal connect --key sk_a1b2c3d4
```

1. 키 유효성 검증 → 바인딩된 bot_id 확인
2. 봇의 전략이 `accepts_external_signals=True`인지 확인
3. 봇이 RUNNING 상태인지 확인
4. 양방향 JSON Lines 스트림 수립 (stdin/stdout)
   - 표준 입력에 리다이렉트한 파일(`< signals.jsonl`)은 파이프와 같이 읽고, 파일이 끝나면 송신 쪽을 닫는다.

**채널이 봇에 전달하는 이벤트**:
- 외부 → Ante: `{"type": "signal", ...}` → ExternalSignalEvent 발행 → `on_data()` 호출
- 외부 → Ante: `{"type": "query", "method": "positions"}` → StrategyContext 경유 조회 → 결과 반환
- 외부 → Ante: `{"type": "ping"}` → `{"type": "pong"}` 응답 (연결 상태 확인)

**채널이 외부에 전달하는 이벤트**:
- Ante → 외부: 체결 통보 (`{"type": "fill", ...}`)
- Ante → 외부: 주문 상태 변경 (`{"type": "order_update", ...}`)
- Ante → 외부: 데이터 조회 응답 (`{"type": "result", ...}`)

**`on_external_signal()` 구현**:

Bot이 ExternalSignalEvent를 수신하면:
1. `event.bot_id`가 자기 것인지 확인
2. 전략의 `meta.accepts_external_signals` 확인 (이중 검증)
3. 봇이 RUNNING인지 확인. 아니면 「외부 시그널 거부」 경고 로그를 남기고 버린다
4. `_signal_lock`을 얻은 뒤 다시 확인. 봇이 RUNNING이 아니거나 시그널이 이 핸들러에 들어온 뒤 다시 시작됐으면(세대 번호가 다르면) 같은 경고 로그를 남기고 버린다
5. `strategy.on_data(event.data)` 호출
6. 반환된 Signal을 `_publish_signals()`로 발행
7. 체결/상태 변경 시 채널을 통해 외부에 통보

### 채널 teardown enforcement (#2334)

> wire/transport 세부(3-phase upgrade, 1:1 framing, `closed.reason` vocab 등)는 [ipc.md](../ipc/ipc.md) streaming 절이 SSOT다. 본 절은 채널 생명주기 **계약**만 정의한다.
> **적용 시점**: 본 enforcement는 **구현 PR 머지 후(동기 버그 #2333 unblock)** 동작한다. 그 전까지 `ante signal connect`는 데몬이 아닌 CLI-프로세스의 `BotManager`를 보므로 데몬에서 RUNNING 중인 봇 채널에 닿지 못한다(현 동작 = #2333 dead-end). 따라서 아래 "즉시 끊김" 계약은 **현재 실행 가능 동작이 아니라 채택된 목표 계약**이다.

기존 스펙은 "키 갱신 시 기존 채널은 즉시 끊긴다"고 단언했으나 **enforcement 메커니즘은 명세되지 않았다**. #2334로 다음을 정규화한다.

**`SignalChannelRegistry`**: 데몬에 상주하는 활성 채널 레지스트리. `bot_id → {session_id → ChannelHandle}` 구조로 활성 시그널 채널을 추적하며, `rotate_signal_key`/`delete_bot`/봇 상태 전이/데몬 shutdown이 봇 단위로 채널을 강제 종료(`close_bot(bot_id, reason)` / `close_all(reason)`)할 수 있게 한다. 데몬 부팅 시 단일 인스턴스를 BotManager·IPC 서버에 공유 주입한다(미사용 환경은 None 허용).

**단일 active connect 정책**: 본 릴리스는 **bot_id당 동시 active 시그널 채널 1개**만 허용한다. 같은 봇에 대한 두 번째 `signal connect` 핸드셰이크는 stable code **`BOT_SIGNAL_CHANNEL_BUSY`**로 거부된다(동시 same-bot 구독의 fan-out·dedup 경합 클래스 제거). 레지스트리는 미래 multi-connect 대비 `session_id` 키를 유지하되, 정책은 현 릴리스에서 single로 잠근다. (코드 분류 SSOT는 [error-taxonomy.md](../contracts/error-taxonomy.md).)

**teardown 트리거**: 오직 rotate/delete만 거는 대신, **봇이 RUNNING을 이탈하는 모든 경로**를 단일 메커니즘으로 덮는다.

| 트리거 | 메커니즘 | `closed.reason` |
|--------|----------|------------------|
| 키 회전 | `rotate_signal_key` — DB rotate **커밋 성공 직후** `close_bot(bot_id, "rotated")`. ROLLBACK 시 teardown 안 함(옛 키 유효) | `rotated` |
| 봇 삭제 | `delete_bot` — `bot.stop()` **호출 전**에 `close_bot(bot_id, "deleted")`(채널이 dead ctx를 pump하지 않도록) | `deleted` |
| 봇 RUNNING 이탈(graceful stop·자율 ERROR·account-suspend·rule-engine stop·auto-restart·`stop_all`) | `BotStoppedEvent`/`BotErrorEvent`를 `bot_id` 필터로 **이벤트-구동** 구독 → 수신 시 `close_bot(bot_id, "bot_stopped")` | `bot_stopped` |
| 데몬 shutdown | shutdown sweep에서 봇 stop·DB close **이전에** `close_all("draining")`(channels-before-bots-before-db 불변) | `draining` |

- teardown hook은 **BotManager 계층**(rotate/delete 메서드·이벤트 구독)에만 둔다. pure-DB primitive(`SignalKeyManager.rotate/revoke`)에는 두지 않는다 — cold-path(서버 정지 상태)에서도 도달하는 경로이기 때문이다.

**rotate→teardown 정밀 보장**: rotate 커밋이 active signal 처리 중에 발생해도 in-flight `strategy.on_data` 체인을 mid-chain cancel하면 전략 상태가 손상된다. 따라서 보장을 다음과 같이 정밀화한다.

1. teardown은 먼저 `accepting=False`를 set하여 이후 inbound signal admit을 거부한다.
2. in-flight publish/`on_data` span은 shield되어 완료된다(mid-chain cancel 금지).
3. 결과 보장 = **"커밋 후 NEW signal은 admit되지 않으며, 옛 키로 진입한 in-flight signal은 최대 1개(at-most-one)까지 정상 완료된다"** — **"in-flight signal abort"가 아니다.** 즉 rotate/delete 직후 새 주문을 유발하는 신규 시그널 주입은 불가능하고, 키 교체에서는 옛 키로 이미 진입한 trailing signal 1개와 그에 따른 trailing fill만 관측될 수 있다. 삭제는 실행 중인 봇이면 `stop()`을 거치므로, 진입한 `on_data`는 끝까지 실행되지만 그것이 돌려준 시그널은 주문 요청으로 발행되지 않는다(위 「정지 뒤의 주문」). 정상 완료되는 1건은 이미 `on_data`를 시작한 시그널이다. `_signal_lock`을 기다리던 시그널은 봇이 RUNNING을 떠났거나 다시 시작됐으면 버려진다(위 「봇 상태 머신」). 송신자가 받는 ack는 처리 여부를 뜻하지 않는다.

이 enforcement는 "직접 DB 수정으로 봇 status/signal key를 바꾸면 `_bots`·실행 task·EventBus 구독·외부 signal channel이 어긋나므로 허용하지 않는다"는 본 문서의 런타임 IPC 위임 원칙(위 참조)과 정합한다.

### 예외 격리 (D-003)

각 Bot은 별도 `asyncio.Task`로 실행되므로, 한 봇에서 예외가 발생해도 다른 봇에 영향을 주지 않는다.

- `_run_loop()` 내부에서 예외 발생 시 해당 봇만 `ERROR` 상태로 전환
- `BotErrorEvent`를 발행하여 알림 트리거
- 다른 봇의 Task는 독립적으로 계속 실행
- `CancelledError`는 재발생시켜 정상 중지 흐름(`stop()`) 유지

### 봇 자동 재시작 정책

BotManager는 봇 에러 발생 시 `BotErrorEvent`를 구독하여 자동 재시작을 수행한다.

**정책**:
- `auto_restart` 설정이 `True`인 봇만 대상
- 쿨다운(`restart_cooldown_seconds`) 대기 후 재시작 시도
- 최대 `max_restart_attempts`회까지 시도
- 한도 소진 시 `BotRestartExhaustedEvent` 발행 → 알림 트리거
- 재시작 성공 후 `cooldown × max_restart_attempts`초 동안 정상 운행하면 카운터 리셋

**관련 메서드**:
- `_on_bot_error()` — 에러 감지 + 재시작 스케줄링
- `_restart_after_cooldown()` — 쿨다운 대기 후 `bot.start()` 재호출
- `_schedule_restart_reset()` — 정상 운행 유지 시 카운터 리셋 타이머
- `_on_restart_exhausted()` — 한도 소진 이벤트 발행
- `get_restart_count(bot_id)` — 현재 재시작 시도 횟수 조회
