# Strategy 모듈 세부 설계 - 설계 결정 - StrategyContext — 전략에 노출되는 제한된 API

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# StrategyContext — 전략에 노출되는 제한된 API

구현: `src/ante/strategy/context.py` 참조

Bot이 생성하여 전략에 주입하는 제한된 시스템 API이다. 전략은 StrategyContext를 통해서만 데이터 조회, 포트폴리오 조회, 주문 관리, 파일 접근, 로깅에 접근한다.

#### StrategyContext 추가 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_trade_history` | `symbol: str \| None = None, limit: int = 50` | `list[dict[str, Any]]` | 봇의 거래 이력 조회 (TradeHistoryView에 위임). 미주입 시 빈 리스트 반환 |
| `load_file` | `path: str` | `bytes` | strategies/ 하위 파일 읽기 (바이너리). 경로 탈출 차단 |
| `load_text` | `path: str, encoding: str = "utf-8"` | `str` | strategies/ 하위 파일 읽기 (텍스트). 경로 탈출 차단 |
| `log` | `message: str, level: str = "info"` | `None` | 전략 전용 로거에 기록 |

**파일 접근 보안**:
- `strategies/` 디렉토리 하위만 접근 허용
- 절대 경로 차단, `../` 등 경로 탈출 시도 시 `StrategyFileAccessError` 발생
- 전략이 학습 데이터, 설정 파일 등을 읽을 때 사용

**설계 근거**:

1. **전략은 StrategyContext를 통해서만 시스템과 상호작용**
   - EventBus, BrokerAdapter, Config 등 시스템 내부에 직접 접근 불가
   - NautilusTrader도 유사 패턴: Strategy가 trading node의 cache/portfolio에 접근하되, 직접 코어를 건드리지 않음

2. **신규 주문은 Signal 반환, 취소/정정은 StrategyContext 메서드**
   - 신규 주문: on_step() → Signal 반환 → Bot이 OrderRequestEvent 발행
   - 취소/정정: ctx.cancel_order() / ctx.modify_order() → 내부 큐 → Bot이 일괄 처리
   - 두 경로 모두 EventBus를 통해 RuleEngine 검증을 거침
   - NautilusTrader는 submit/cancel/modify 모두 전략 메서드로 직접 호출 — Ante도 취소/정정은 메서드 방식 채택 (기존 order_id를 참조해야 하므로 Signal 반환보다 자연스러움)

3. **DataProvider 추상화**
   - 라이브 모드: API Gateway를 통한 실시간 데이터
   - 백테스트 모드: Parquet에서 로드한 과거 데이터
   - 전략 코드 수정 없이 두 모드에서 동일하게 동작

4. **PortfolioView (읽기 전용)**
   - 전략이 포지션/잔고를 조회만 가능, 직접 변경 불가
   - 변경은 주문 체결 시 Treasury가 자금 정산, Trade 모듈이 포지션 업데이트 수행
