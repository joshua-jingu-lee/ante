# Strategy 모듈 세부 설계 - 설계 결정 - 전략 운용 방식

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 전략 운용 방식

전략은 매매 로직의 위치에 따라 세 가지 방식으로 운용된다:

| 방식 | 전략 파일 | 외부 에이전트 | 핵심 진입점 |
|------|----------|-------------|-----------|
| **인하우스** | 판단 로직 전부 | 없음 | `on_step()` |
| **하이브리드** | 판단 로직 일부 + 외부 데이터 수신 | 보조 데이터 제공 | `on_step()` + `on_data()` |
| **아웃소싱** | 빈 껍데기 (중계 전용) | 판단 전부 | `on_data()` |

**설계 근거**:

1. **인하우스**: Ante가 제공하는 데이터(OHLCV, 지표, 포지션)만으로 전략 파일 안에 자체 로직을 구현. 전략 파일이 금지 모듈 검증과 샌드박스 안에서 완결적으로 동작
2. **아웃소싱**: 전략 파일은 브릿지 역할만 하고, 외부 에이전트가 모든 판단을 수행하여 시그널만 전송. 외부 에이전트는 Ante의 샌드박스 제약 없이 자유롭게 네트워크·LLM·크롤링 등을 활용. `meta.accepts_external_signals = True` 선언 필수
3. **하이브리드**: 자체 기술적 분석 + 외부 뉴스 감성 점수 등을 결합. 두 진입점을 모두 활용

세 방식 모두 최종적으로 동일한 경로를 탄다: `Signal → OrderRequestEvent → RuleEngine → 주문 실행`

#### 외부 시그널 채널

아웃소싱/하이브리드 전략을 위해, 외부 에이전트와 봇 사이에 **양방향 시그널 채널**을 제공한다. 채널은 봇 생성 시 발급되는 **시그널 키**로 바인딩되며, CLI 파이프 기반으로 동작한다.

**시그널 키**:
- 봇 생성 시 `accepts_external_signals=True`인 전략이면 시그널 키 자동 발급
- 키는 봇+전략 조합에 바인딩 — 해당 봇에만 접근 가능
- 키 폐기/재발급(rotate) 지원
- 키 없이는 시그널 전송 불가

**CLI 파이프 채널**:
```bash
# 채널 연결 — Ante 프로세스와 양방향 JSON 라인 스트림 수립
ante signal connect --key sk_a1b2c3d4
```

**양방향 통신 (JSON Lines 프로토콜)**:
```
# 외부 → Ante: 시그널 전송
→ {"type": "signal", "symbol": "005930", "side": "buy", "quantity": 10, "reason": "..."}

# Ante → 외부: 체결 통보
← {"type": "fill", "order_id": "ORD-001", "symbol": "005930", "side": "buy", "qty": 10, "price": 58200}

# 외부 → Ante: 데이터 조회 요청
→ {"type": "query", "method": "positions"}
← {"type": "result", "data": {"005930": {"quantity": 10, "avg_price": 58200}}}

→ {"type": "query", "method": "ohlcv", "params": {"symbol": "005930", "timeframe": "1d", "limit": 10}}
← {"type": "result", "data": [...]}
```

**키 기반 접근 범위**:

| 데이터 | 접근 가능 | 이유 |
|--------|----------|------|
| 이 봇의 포지션/체결 | O | 키에 바인딩된 봇 소속 |
| 이 봇의 잔고 | O | 동일 |
| 시세 데이터 (OHLCV) | O | 공개 데이터 |
| 다른 봇의 포지션 | X | 키 범위 밖 |
| 시스템 설정/전역 상태 | X | 키 범위 밖 |

**채널을 통한 이벤트 플로우**:
```
외부 에이전트 → CLI 파이프 → ExternalSignalEvent → EventBus
  → Bot.on_external_signal() → strategy.on_data() → Signal → 주문 실행
  → 체결/상태 변경 → CLI 파이프 → 외부 에이전트
```

**설계 근거**:

1. **CLI 파이프 (HTTP API 대신)**: Ante는 개인 홈서버용 시스템. 외부 에이전트를 위해 HTTP 서버를 별도 노출할 필요 없이, 로컬 프로세스 통신으로 충분. 네트워크 공격면 없음
2. **시그널 키**: `accepts_external_signals=False`인 전략에 시그널이 전송되는 것을 사전 차단. 키가 봇+전략 조합에 바인딩되므로 다른 봇에 접근 불가
3. **양방향**: 외부 에이전트가 Ante의 데이터(포지션, 시세, 체결)를 조회하여 판단 근거로 활용. 이로써 전략 파일에서 금지된 네트워크 호출(requests, httpx 등) 없이도 외부 에이전트가 충분한 정보를 확보
4. **금지 모듈 방어 유지**: 외부 데이터 접근은 샌드박스 바깥의 외부 에이전트가 담당하므로, 전략 파일 내 금지 모듈 검증은 그대로 유지

#### 아웃소싱 전략 예시

```python
class AgentRelay(Strategy):
    """외부 에이전트의 시그널을 중계하는 브릿지 전략."""

    meta = StrategyMeta(
        name="agent_relay",
        version="1.0.0",
        description="외부 에이전트 시그널 중계 전용",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []  # 자체 판단 없음

    async def on_data(self, data: dict[str, Any]) -> list[Signal]:
        return [Signal(
            symbol=data["symbol"],
            side=data["side"],
            quantity=data["quantity"],
            order_type=data.get("order_type", "market"),
            price=data.get("price"),
            stop_price=data.get("stop_price"),
            reason=data.get("reason", "external agent signal"),
        )]
```
