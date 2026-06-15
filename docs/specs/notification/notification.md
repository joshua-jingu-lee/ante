# Notification Adapter 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/notification/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 알림, [eventbus.md](../eventbus/eventbus.md) NotificationEvent

## 개요

Notification Adapter는 **`NotificationEvent`를 외부 알림 채널로 전달하는 모듈**이다.
초기 구현은 텔레그램을 지원하며, 알림 채널은 모듈화하여 향후 교체·추가 가능하게 설계한다.

**핵심 원칙: 메시지 생성은 각 모듈, 발송은 Notification 모듈**

각 모듈(bot, trade, broker 등)이 알림 메시지를 직접 작성하여 `NotificationEvent`로 발행한다. NotificationService는 이벤트를 수신하여 레벨 필터링, 중복 억제, 발송만 담당한다. Notification 모듈은 메시지 내용을 알 필요가 없다.

**주요 기능**:
- **NotificationAdapter ABC**: 채널별 구현체의 표준 계약
- **TelegramAdapter**: 텔레그램 봇 API 기반 알림 발송. 레벨별 이모지 자동 부여
- **NotificationService**: `NotificationEvent` 구독 → 필터링 → 발송
- **알림 레벨**: critical / error / warning / info — 레벨별 필터링
- **무음 시간대**: `notification.quiet_hours` 설정으로 비긴급 알림 억제
- **알림 중복 억제**: dedup_window 기반 동일 메시지 억제
- **TelegramCommandReceiver**: 텔레그램 봇 명령 수신 (양방향 통신)

## 설계 결정

### NotificationEvent 인터페이스

각 모듈이 발행하는 알림 이벤트의 표준 인터페이스. 모듈은 순수 텍스트만 작성하며, 이모지와 Markdown 서식은 TelegramAdapter가 level 기반으로 자동 부여한다.

```python
NotificationEvent(
    level="error",              # 알림 레벨 (필수): critical / error / warning / info
    title="봇 에러",             # 짧은 제목 (필수)
    message="봇 bot-001에서...", # 본문 (필수)
    category="bot",             # 도메인 (필터링/이력 조회용)
)
```

### NotificationLevel Enum

| 값 | 설명 | 용도 | 이모지 |
|----|------|------|--------|
| CRITICAL | 긴급 | 킬 스위치, 포지션 불일치 | 🚨 |
| ERROR | 에러 | 봇 에러, 주문 실패, 서킷 브레이커 차단 | ❌ |
| WARNING | 경고 | 인증 실패, 서킷 브레이커 복구 | ⚠️ |
| INFO | 정보 | 체결 완료, 봇 시작/중지, 결재, 시스템 시작/종료 | ℹ️ |

### NotificationAdapter ABC

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async send` | level: NotificationLevel, message: str | bool | 알림 발송. 성공 시 True |
| `async send_rich` | level: NotificationLevel, title: str, body: str, metadata: dict \| None | bool | 서식이 있는 알림 발송 (제목 + 본문 + 메타데이터) |
| `async send_with_buttons` | level: NotificationLevel, message: str, buttons: list[list[dict]] | bool | 인라인 키보드 버튼 포함 메시지 발송 |

구현: `src/ante/notification/base.py`, `src/ante/notification/telegram.py`

### NotificationService — 발송 + 필터링 + 이력

NotificationService는 `NotificationEvent`만 구독하여 발송한다. 개별 이벤트(BotErrorEvent 등)는 구독하지 않는다.

**생성자 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `adapter` | NotificationAdapter | (필수) | 알림 채널 구현체 |
| `eventbus` | EventBus | (필수) | 이벤트 구독 대상 |
| `min_level` | NotificationLevel | INFO | 최소 알림 레벨 |
| `quiet_start` | time \| None | None | 무음 시작 시각 |
| `quiet_end` | time \| None | None | 무음 종료 시각 |
| `dedup_window` | float | 60.0 | 중복 알림 억제 윈도 (초) |
| `telegram_enabled` | bool | True | 텔레그램 알림 활성화 여부. False여도 CRITICAL은 발송 |

**메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `subscribe` | — | None | `NotificationEvent`와 `ConfigChangedEvent` 구독 등록 |
| `_on_notification` | event: NotificationEvent | None | 필터링 → 발송 |
| `_on_config_changed` | event: ConfigChangedEvent | None | `notification.telegram_enabled`, `notification.min_level`, `notification.quiet_hours` 런타임 반영 |
| `_should_send` | level: NotificationLevel | bool | 발송 여부 판단. CRITICAL은 always-send |
| `parse_quiet_hours` | value: str | tuple[time, time] \| None | `HH:MM-HH:MM` 형식 파싱. invalid이면 None |

구현: `src/ante/notification/service.py`

### 런타임 알림 설정

알림 설정의 SSOT는 Config의 `dynamic_config`다. NotificationService는 시작 시
아래 키를 읽고, 이후 `ConfigChangedEvent`를 통해 재시작 없이 갱신한다.

| 키 | 값 | 동작 |
|----|----|------|
| `notification.telegram_enabled` | `"true"` / `"false"` | `false`이면 CRITICAL 외 알림을 발송하지 않는다. Telegram 시크릿이 존재하면 서비스는 계속 살아 있어 런타임 재활성화와 CRITICAL 발송 경로를 유지한다 |
| `notification.min_level` | `"critical"` / `"error"` / `"warning"` / `"info"` | 최소 발송 레벨. 낮은 우선순위 알림은 발송하지 않는다 |
| `notification.quiet_hours` | `"23:00-07:00"` 또는 빈 값 | 지정 시간대에는 CRITICAL 외 알림을 발송하지 않는다. 빈 값은 비활성화, invalid 형식은 경고 후 비활성화로 처리한다 |

세부 알림 정책 키(`notification.telegram_level`, `notification.on_fill`,
`notification.fill_alert`, `notification.daily_report`)는 1.0 계약에 포함하지 않는다.
체결 알림만 끄기, 일일 리포트만 켜기 같은 정책은 후속 스펙에서 별도 정의한다.

`TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_CHAT_ID`가 없거나 빈 문자열이면 Telegram 어댑터를
생성할 수 없으므로 NotificationService를 생성하지 않고 서버 부팅은 계속한다.
CRITICAL 알림은 `telegram_enabled=false`, `min_level`, `quiet_hours`, dedup을 모두
우회하여 항상 발송한다.

### 알림 트리거 전체 목록

각 알림의 메시지 생성 책임은 해당 모듈에 있다. 아래는 전체 알림 목록과 담당 모듈의 매핑이다.

| 트리거 | 담당 모듈 | 레벨 | category |
|--------|----------|------|----------|
| 거래 상태 변경 (킬 스위치) | account (AccountService) | CRITICAL | system |
| 포지션 불일치 | broker (Reconciler) | CRITICAL | broker |
| 봇 에러 | bot (BotManager) | ERROR | bot |
| 봇 재시작 한도 소진 | bot (BotManager) | ERROR | bot |
| 주문 취소 실패 | trade (TradeRecorder) | ERROR | trade |
| 서킷 브레이커 차단 | broker (KISAdapter) | ERROR | broker |
| 인증 실패 반복 | member (AuthService) | WARNING | member |
| 서킷 브레이커 복구 | broker (KISAdapter) | INFO | broker |
| 체결 완료 (매수/매도) | trade (TradeRecorder) | INFO | trade |
| 결재 요청 생성 | approval (ApprovalService) | INFO | approval |
| 결재 처리 완료 | approval (ApprovalService) | INFO | approval |
| 전략 채택 (REGISTERED→ADOPTED) | approval (executor) | INFO | strategy |
| 전략 폐기 (→ARCHIVED) | approval (executor) | INFO | strategy |
| 봇 시작 | bot (BotManager) | INFO | bot |
| 봇 중지 | bot (BotManager) | INFO | bot |
| 일일 성과 요약 | trade (스케줄 트리거) | INFO | trade |
| 시스템 시작 | core (main) | INFO | system |
| 시스템 종료 | core (main) | INFO | system |

> 각 모듈의 예시 메시지는 해당 모듈의 알림 이벤트 정의 또는 텔레그램 명령 응답 섹션에 기재한다.
> [bot.md](../bot/bot.md), [trade.md](../trade/trade.md), [core.md](../core/core.md), [broker-adapter.md](../broker-adapter/broker-adapter.md), [approval.md](../approval/approval.md), [member.md](../member/member.md)

### TelegramCommandReceiver — 텔레그램 명령 수신

> 소스: [`src/ante/notification/telegram_receiver.py`](../../../src/ante/notification/telegram_receiver.py)

텔레그램 봇의 `getUpdates` long-polling으로 사용자 명령을 수신하는 양방향 통신 모듈. `TelegramAdapter`와 동일한 bot_token/chat_id를 공유한다.

**생성자 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `adapter` | TelegramAdapter | (필수) | 텔레그램 어댑터 (API base URL 공유) |
| `enabled` | bool | True | 명령 수신 활성화 여부. `TELEGRAM_CHAT_ID`를 허용 사용자로 사용 |
| `polling_interval` | float | 3.0 | 폴링 간격 (초) |
| `confirm_timeout` | float | 30.0 | 위험 명령 확인 대기 시간 (초) |
| `bot_manager` | BotManager \| None | None | 봇 관리용 |
| `treasury_manager` | TreasuryManager \| None | None | 자금 현황 조회용 (전 계좌) |
| `account_service` | AccountService \| None | None | 계좌 상태 제어용 |
| `approval_service` | ApprovalService \| None | None | 결재 승인/거절 처리용 |
| `instrument_service` | InstrumentService \| None | None | `/stop` 보유종목 종목명 병기용 (#2385) |

**지원 명령:**

| 명령 | 설명 | 확인 필요 |
|------|------|----------|
| `/help` | 사용 가능한 명령어 목록 | - |
| `/status` | 시스템 상태 요약 (거래 상태, 봇 현황) | - |
| `/bots` | 봇 목록 + 상태 | - |
| `/balance` | 전 계좌 자금 현황 요약 (계좌별 잔고, 할당/미할당) | - |
| `/halt [reason]` | 전체 거래 중지 (모든 ACTIVE 계좌를 SUSPENDED로 전환) | 2단계 확인 |
| `/clear_halt` | 전역 정지 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 봇 자동 재시작 아님) | 2단계 확인 |
| `/stop <bot_id>` | 특정 봇 중지 | 2단계 확인 |
| `/confirm` | 위험 명령 확인 | - |

**2단계 확인**: `halt`, `clear_halt`, `stop` 명령은 `_DANGEROUS_COMMANDS`로 분류되며, `/confirm` 입력 후 `confirm_timeout` 내에서만 실행된다. `/clear_halt`는 계좌 상태만 ACTIVE로 복구하며 봇을 자동 재시작하지 않는다.

**`/stop` 보유종목 출력 (#2385)**: 봇 중지 후 유지되는 보유종목을 표기할 때 종목코드만 나열하지 않고 `InstrumentService.format_label` SSOT(`docs/specs/instrument/instrument.md` 참조)를 따라 `{symbol} (종목명)`을 병기한다. `_reply()`는 `parse_mode`를 설정하지 않는 **plain transport**이므로 `format_label(symbol, exchange, markdown=False)`로 호출한다. exchange는 `bot.config.account_id` → `account_service.get(...).exchange`로 해석하되 실패/미주입 시 `KRX`로 폴백한다. `instrument_service` 미주입 시 종목코드만 표기하는 기존 경로를 유지한다(graceful fallback). plain 모드도 종목명을 escape하므로 특수문자를 포함한 종목명은 백슬래시가 리터럴로 보일 수 있으나, 이는 bounded known-limitation으로 수용한다(`_reply` transport 및 `format_label` escape 계약은 multi-consumer 표면이라 본 범위 비목표).

**결재 처리**: 결재 승인/거절은 텍스트 명령이 아니라 결재 요청 알림에 첨부된 인라인 [승인]/[거절] 버튼 callback으로만 처리한다 (아래 [결재 인라인 버튼](#결재-인라인-버튼) 참조). 텔레그램 텍스트 명령 `/approve`·`/reject`는 지원하지 않는다.

**보안**: `TELEGRAM_CHAT_ID`와 일치하지 않는 사용자의 명령은 무시하고 로그에 기록한다.

### 결재 인라인 버튼

결재 요청 알림 발송 시 Telegram `InlineKeyboardButton`으로 [승인] [거절] 버튼을 메시지에 첨부한다. 사용자가 버튼을 탭하면 `callback_query`로 수신되어 `ApprovalService.approve()` / `reject()`를 호출한다.

**흐름:**

```
Approval 모듈이 NotificationEvent 발행 (buttons 포함)
  → NotificationService._on_notification()
    → TelegramAdapter.send_with_buttons()
      → 메시지 + InlineKeyboardMarkup:
        [✅ 승인] callback_data="approve:{id}"
        [❌ 거절] callback_data="reject:{id}"

사용자가 버튼 탭
  → Telegram callback_query 수신
    → TelegramCommandReceiver._handle_callback_query()
      → ApprovalService.approve(id) 또는 reject(id)
      → answerCallbackQuery + 결과 메시지 발송
```

**거절 사유 입력:** 인라인 버튼으로 거절 시 기본 사유("사용자 거절")를 사용한다. 상세 사유가 필요하면 CLI(`ante approval reject <id> --reason <reason>`)로 처리한다.

### 텔레그램 처리 응답과 NotificationEvent 중복 방지

텔레그램에서 처리된 작업(`/stop`, `/halt`, `/clear_halt` 등 명령 및 결재 인라인 버튼 callback `approve:{id}`/`reject:{id}`)은 `TelegramCommandReceiver`가 직접 응답(reply)을 발송한다. 이때 동일 내용의 `NotificationEvent`를 발행하면 사용자가 같은 채널에서 메시지를 2번 수신하게 된다.

**정책**: 텔레그램에서 트리거된 작업은 직접 응답만 발송하고, `NotificationEvent`는 발행하지 않는다(`suppress_notification=True`). CLI 등 텔레그램 외 채널에서 처리된 경우에만 `NotificationEvent`를 발행한다. 즉 "1회 응답"은 NotificationEvent 중복을 억제한다는 의미이며, 직접 응답 자체의 횟수 제한이 아니다.

```
텔레그램에서 처리 → 직접 응답(reply)만 발송, NotificationEvent 생략 → 1회
CLI에서 처리 → NotificationEvent 발행 → 텔레그램 도착 → 1회
```

이를 통해 사용자는 어떤 채널에서 처리하든 정확히 1번만 메시지를 수신한다.

> 각 모듈별 텔레그램 명령 응답 형식은 해당 스펙 문서의 알림 이벤트 정의 또는 텔레그램 명령 응답 섹션에 기재한다.

### 알림 중복 억제 (Dedup)

`dedup_window` 초 내에 동일 내용의 알림을 억제한다. MD5 해시 기반으로 `(level, message)` 조합을 추적하며, 억제된 알림 수를 다음 발송 시 `"(N건 억제됨)"` 형태로 메시지에 병기한다. **CRITICAL 레벨 알림은 중복 억제를 우회하여 항상 발송된다.**

## 타 모듈 설계 시 참고

- **Config 스펙**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`는 secrets.env에서 관리. `notification.telegram_enabled`, `notification.min_level`, `notification.quiet_hours`는 dynamic_config에서 관리
- **CLI/IPC 스펙**: 동적 설정 명령으로 `notification.telegram_enabled`, `notification.min_level`, `notification.quiet_hours`를 변경
- **EventBus 스펙**: `NotificationEvent`에 `category` 필드 추가, `SystemStartedEvent` 신규 생성
