# Broker Adapter 모듈 세부 설계 - BROKER_REGISTRY — 브로커 타입 레지스트리

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# BROKER_REGISTRY — 브로커 타입 레지스트리

구현: `src/ante/broker/registry.py` 참조

`broker_type` 문자열을 어댑터 클래스로 매핑하는 딕셔너리.

정의: `ante.broker.registry.BROKER_REGISTRY` (코드가 정본이다).

- `BROKER_REGISTRY`: "kis-overseas"는 1.1에서 등록. 현재 미등록.

키와 값: `test` → `TestBrokerAdapter`, `kis-domestic` → `KISDomesticAdapter`, `mock` → `MockBrokerAdapter`.

미등록 `broker_type` 요청 시 `InvalidBrokerTypeError`를 발생시킨다.

브로커 타입 레지스트리는 두 곳에 있다. 이 `BROKER_REGISTRY`는 CLI의 `--broker-type` 검증에 쓰이고, `AccountService.get_broker()`의 어댑터 생성은 `account/service.py`의 `_BROKER_REGISTRY`([account/03-data-model.md](../account/03-data-model.md#broker_registry))가 맡는다. 두 레지스트리와 `BROKER_PRESETS`([06-broker-presets.md](06-broker-presets.md))의 키 집합은 같아야 한다.

`mock`과 `test`는 가상 계좌 전용이다. 조합 제약은 [12-test-broker-adapter.md](12-test-broker-adapter.md#가상-전용), `mock`의 가격 주입은 [12-test-broker-adapter.md](12-test-broker-adapter.md#브로커-타입-mock)를 따른다.
