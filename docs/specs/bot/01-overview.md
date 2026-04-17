# Bot 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 개요

Bot 모듈은 **전략을 로드하여 독립적인 asyncio.Task로 실행하는 거래 실행 엔진**이다.
각 봇은 Strategy 인스턴스를 생성하고, 주기적으로 `on_step()`을 호출하여 매매 시그널을 수집한 뒤,
Signal을 OrderRequestEvent로 변환하여 EventBus에 발행한다.

**주요 기능**:
- **BotManager**: 봇들의 생명주기(생성·시작·중지·삭제)를 중앙 관리
- **Bot**: 전략 실행 루프 — `on_step()` 호출, Signal → OrderRequestEvent 변환, 체결 통보 전달
- **봇 단위 예외 격리**: 각 봇은 독립 asyncio.Task, 한 봇의 오류가 타 봇에 무영향 (D-003)
- **계좌 소속**: 각 봇은 반드시 하나의 Account에 소속되며, Account의 trading_mode(LIVE/VIRTUAL)에 따라 실행 경로가 결정됨
- **상태 관리**: 봇별 실행 상태, 설정, 성능 지표를 SQLite에 영속화
