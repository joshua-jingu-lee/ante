# Broker Adapter 모듈 세부 설계 - 스펙 아웃 (Scope-out)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 스펙 아웃 (Scope-out)

### 실시간 스트리밍 (`realtime_price_stream`, `realtime_order_stream`)

오픈 시점에는 실시간 WebSocket 스트리밍을 포함하지 않는다. `BrokerAdapter` 추상 인터페이스 및 `KISBrokerAdapter`의 해당 스텁 메서드는 제거 대상이다. 향후 필요 시 별도 스펙으로 설계한다.

### KISOverseasAdapter 구현

1.1 범위. 이 문서에서는 KISBaseAdapter의 확장 포인트와 국내/해외 분리 요약만 정의한다. `BROKER_REGISTRY`에 `kis-overseas`를 등록하지 않으며, 구현체는 1.1에서 작성한다.
