# Broker Adapter 모듈 세부 설계 - BROKER_REGISTRY — 브로커 타입 레지스트리

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# BROKER_REGISTRY — 브로커 타입 레지스트리

구현: `src/ante/broker/registry.py` 참조

`broker_type` 문자열을 어댑터 클래스로 매핑하는 딕셔너리. `AccountService.get_broker()`에서 계좌의 `broker_type`으로 어댑터를 인스턴스화할 때 사용한다.

```python
BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {
    "test": TestBrokerAdapter,
    "kis-domestic": KISDomesticAdapter,
    # "kis-overseas"는 1.1에서 등록. 현재 미등록.
}
```

미등록 `broker_type` 요청 시 `InvalidBrokerTypeError`를 발생시킨다.
