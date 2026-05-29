# Broker Adapter 모듈 세부 설계 - 스펙 아웃 (Scope-out)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 스펙 아웃 (Scope-out)

### 실시간 시세 스트리밍 (`realtime_price_stream`)

오픈 시점에는 실시간 가격 스트리밍을 필수 범위로 포함하지 않았다. 이후
`KISStreamClient`가 추가되어 실시간 시세 스트리밍과 REST 폴백을 지원한다
([api-gateway](../api-gateway/api-gateway.md), `gateway/stream_integration.py`).

### 체결 통보 (`realtime_order_stream`) — 정정 (#1946)

> **정정**: 아래는 더 이상 정확하지 않다. 체결 통보는 실시간 스트림
> (`H0STCNI0`, 빠른 경로)에 더해 **REST `get_order_history` 백스톱 폴**로
> 정합성이 보증된다. 체결→포지션 반영은 스트림 유무·모의투자·실전투자 무관하게
> 일관된다. 설계 SSOT는 [18-fill-recovery.md](18-fill-recovery.md)다.

(이전 서술) 오픈 시점에는 실시간 체결 통보 스트리밍을 필수 범위에 포함하지
않았다. 정합성은 #1946에서 REST 백스톱(`FillReconcileScheduler`) +
`OrderTracker` + `FillApplier`로 확보했으며, 스트림은 선택적 저지연 경로다.

일반 운영 CLI의 `ante broker stream prices`도 오픈 범위에 포함하지 않는다. 실시간
가격 스트리밍이 필요하면 WebSocket/streaming 설계와 함께 서버 BrokerAdapter를 통한
런타임 IPC 또는 별도 stream server 계약을 먼저 정의한다.

### 직접 broker 주문 CLI

일반 운영 CLI의 `ante broker order`는 제공하지 않는다. 수동 주문 테스트는
Bot/Strategy → RuleEngine → BrokerAdapter 경로를 우회할 수 있으므로, 별도
maintenance/test 스펙에서 승인, 감사 로그, virtual/live 운용 보호 장치, 권한 scope를 정한
뒤에만 도입한다.

### KISOverseasAdapter 구현

1.1 범위. 이 문서에서는 KISBaseAdapter의 확장 포인트와 국내/해외 분리 요약만 정의한다. `BROKER_REGISTRY`에 `kis-overseas`를 등록하지 않으며, 구현체는 1.1에서 작성한다.
