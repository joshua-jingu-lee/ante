# Bot 모듈 세부 설계 - CLI 사용법

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# CLI 사용법

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#커맨드-상세)다. 이 문서는 Bot 관점의
운영 흐름만 설명한다. 입력 계약(비대화형 옵션 기반, 위험 명령 `--yes` 요구)은
[cli/02-design-decisions.md — 비대화형 입력 계약](../cli/02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract)을 따른다.

봇의 생성·시작·중지와 signal key 갱신은 서버 BotManager의 인메모리 상태, 실행 task,
EventBus 구독, 외부 signal channel에 영향을 주므로 런타임 IPC로 처리한다. `bot remove`는
서버 실행 중에는 IPC로 BotManager에 위임하고, 서버 정지 중에는 cold-path cleanup으로
DB의 persisted state를 직접 정리한다. 서버 실행 중 조회는 IPC로 live 상태를 우선
조회하고, 서버 정지 중에는 DB에 저장된 persisted snapshot만 조회한다.

> **미구현 (follow-up)**: `ante bot start`/`bot stop`/`bot status`는 CLI command 및
> 대응 IPC handler(`bot.start`/`bot.stop` mutating + `bot.status` status 조회)가
> 등록되어 있지 않다. `BotManager.start_bot()`/`stop_bot()` 코드는 실재하나
> CLI(Click)·IPC wiring이 별도 follow-up이다. `bot.query` 계열 조회 경로는
> 실재 `list/info/positions/signal-key` CLI에 대해 동작하므로 미구현이 아니다.
> 아래 사용 예시의 `bot start`/`bot stop`/`bot status` 라인은 설계
> 의도이며 현재 실행 불가다. 현재 실재 bot CLI는
> `create/info/list/positions/remove/signal-key`.

```bash
# 전략 등록 후 봇 생성 — --account 필수 옵션 (active 계좌가 정확히 1개일 때만 생략 가능, 자동 선택)
# active 계좌가 0개 또는 2개 이상이면 prompt 없이 BOT_MISSING_REQUIRED_ACCOUNT로 실패한다.
ante strategy submit strategies/momentum_breakout.py
ante bot create --name "Momentum Bot" --strategy momentum_breakout_v1.0.0 --account domestic --interval 60
ante bot create --name "Agent Relay" --strategy agent_relay_v1.0.0 --account us-stock
# → bot_id: bot_002, signal_key: sk_a1b2c3d4 (외부 시그널 수신 가능)

# 봇 시작 — 미구현 (follow-up): CLI command·IPC handler 미등록
ante bot start bot_001

# 봇 목록 조회
ante bot list
ante bot list --account domestic         # 계좌별 필터
ante bot list --format json

# 봇 상태 조회 — 미구현 (follow-up): CLI command·IPC handler 미등록
ante bot status bot_001

# 봇 중지 — 미구현 (follow-up): CLI command·IPC handler 미등록
ante bot stop bot_001

# 봇 삭제 — --yes 필수. 서버 실행 중이면 IPC, 서버 정지 중이면 cold-path cleanup
# --yes 누락 시 prompt 없이 CLI_CONFIRMATION_REQUIRED로 실패한다.
ante bot remove bot_001 --yes

# 시그널 키 관리
ante bot signal-key bot_002              # 키 조회
ante bot signal-key bot_002 --rotate     # 키 재발급

# 외부 시그널 채널 연결 (양방향 JSON Lines 파이프)
ante signal connect --key sk_a1b2c3d4
```

`bot create`의 `--account` 생략 정책:

- active 계좌가 정확히 1개면 자동 선택을 허용한다.
- active 계좌가 0개 또는 2개 이상이면 prompt 기반 선택 없이 `BOT_MISSING_REQUIRED_ACCOUNT`로 실패한다.
- prompt 기반 계좌 선택 경로는 제공하지 않는다.

cold-path `bot remove`는 BotManager를 만들지 않으며, `signal_keys` 행 삭제,
전략 스냅샷 정리, Treasury budget 환수, `bots.status='deleted'` 갱신만 수행한다.
VirtualExecutor unregister, EventBus 구독 해제, `BotStoppedEvent` 발행은 서버 정지
상태에서 대상 인메모리 객체가 없으므로 수행하지 않는다. cold-path에서
`running`/`stopping` 상태는 stale status로 간주하며 포지션 청산은 지원하지 않는다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
