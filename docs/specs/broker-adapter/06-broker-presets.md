# Broker Adapter 모듈 세부 설계 - BROKER_PRESETS — 브로커 기본값 프리셋

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# BROKER_PRESETS — 브로커 기본값 프리셋

구현: `src/ante/account/presets.py` 참조

브로커별 기본값을 정의하는 프리셋 딕셔너리. 계좌 생성 시 브로커 선택만으로 거래소, 통화, 수수료 등을 자동으로 채운다. 사용자가 명시적으로 지정하지 않은 필드는 프리셋 기본값이 적용된다.

| broker_type | exchange | currency | timezone | trading_hours | buy_commission | sell_commission |
|-------------|----------|----------|----------|--------------|----------------|----------------|
| `test` | `TEST` | `KRW` | `Asia/Seoul` | 00:00–23:59 | 0 | 0 |
| `kis-domestic` | `KRX` | `KRW` | `Asia/Seoul` | 09:00–15:30 | 0.015% | 0.195% |
| `kis-overseas` | `NYSE` | `USD` | `America/New_York` | 09:30–16:00 | 0.1% | 0.1% |
