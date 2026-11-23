# Broker Adapter 모듈 세부 설계 - BROKER_PRESETS — 브로커 기본값 프리셋

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# BROKER_PRESETS — 브로커 기본값 프리셋

구현: `src/ante/account/presets.py` 참조

브로커별 기본값을 정의하는 프리셋 딕셔너리. 계좌 생성 시 브로커 선택만으로 거래소, 통화, 수수료 등을 자동으로 채운다. 사용자가 명시적으로 지정하지 않은 필드는 프리셋 기본값이 적용된다.

| broker_type | exchange | currency | timezone | trading_hours | buy_commission | sell_commission |
|-------------|----------|----------|----------|--------------|----------------|----------------|
| `test` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 |
| `kis-domestic` | `KRX` | `KRW` | `Asia/Seoul` | 09:00–15:30 | 0.015% | 0.195% |
| `mock` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 |

`kis-overseas` 프리셋은 1.0에서 정의하지 않는다([account/03-data-model.md](../account/03-data-model.md#broker_presets)). 해외 어댑터([09-kis-overseas-adapter.md](09-kis-overseas-adapter.md))와 함께 1.1에서 추가한다.

`mock` 프리셋의 나머지 값은 시장가 예약 버퍼 0, 기본 계좌 id `mock`, 기본 이름 `모의`, 필수 자격증명 없음(`[]`)이다. 전체 필드는 [account/03-data-model.md](../account/03-data-model.md#broker_presets)의 프리셋 표를 따른다.

프리셋 수수료는 어댑터 config와 Treasury에만 쓰인다. 가상 계좌의 체결 수수료는 프리셋이 아니라 `VirtualExecutor`의 기본값(매수 0.015%, 매도 0.015% + 세금 0.23%)이다. `test`와 `mock`을 포함해 브로커 타입과 상관없이 같다. 그래서 수수료 0 프리셋의 가상 계좌는 예약(수수료 0)과 체결(기본 수수료)의 비용이 다르다.
