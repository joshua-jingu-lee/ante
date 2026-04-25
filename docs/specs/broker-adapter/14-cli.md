# Broker Adapter 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# CLI 인터페이스

증권사 live 상태를 읽는 CLI 명령은 서버가 시작 시 생성한 BrokerAdapter를 통해
실행하는 런타임 IPC 커맨드다. CLI가 별도 adapter를 직접 생성하면 credentials 복호화,
연결 세션, rate limit, circuit breaker, audit 경로가 서버와 분리된다.

```bash
# 연결 상태 확인
ante broker status [--account domestic]
ante broker health [--account domestic]     # status alias

# 잔고 조회
ante broker balance [--account domestic]

# 포지션 조회
ante broker positions [--account domestic]

# live 현재가 조회
ante broker price <symbol> [--account domestic]

# 포지션 대사
ante broker reconcile [--account domestic] [--fix]
```

`broker price`는 live broker quote만 의미한다. historical/public market data 조회는
`data` 또는 `feed` 계열 커맨드가 담당한다.

일반 운영 CLI는 `broker order`를 제공하지 않는다. 주문은 Bot/Strategy → RuleEngine
→ BrokerAdapter 경로로만 들어가야 하며, 수동 주문 테스트가 필요하면 별도
maintenance/test 스펙에서 승인·감사·실계좌 보호 조건을 정의한다. 실시간 가격
스트리밍 CLI도 오픈 범위가 아니다.
