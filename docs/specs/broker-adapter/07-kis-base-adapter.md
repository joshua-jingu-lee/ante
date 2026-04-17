# Broker Adapter 모듈 세부 설계 - KISBaseAdapter — KIS 공통 레이어

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# KISBaseAdapter — KIS 공통 레이어

구현: `src/ante/broker/kis.py` 참조

KISBaseAdapter는 한국투자증권 Open API의 국내/해외 공통 로직을 추상화하는 중간 계층이다. `BrokerAdapter`를 상속하며, 시장별 서브클래스(`KISDomesticAdapter`, `KISOverseasAdapter`)가 이를 상속한다.

### 공통 로직

| 항목 | 설명 |
|------|------|
| OAuth2 인증 | 토큰 발급·갱신·만료 관리 (동일 APP KEY) |
| HTTP 클라이언트 | aiohttp 세션, 헤더 구성, 에러 파싱 |
| Rate Limiter 연동 | APIGateway의 rate limiter 사용 |
| CircuitBreaker | 장애 감지·차단·복구 상태 머신 |
| 재시도 로직 | 지수 백오프 + 에러 분류 기반 재시도 |
| Base URL 결정 | `broker_config.is_paper`에 따라 실전/모의 도메인 분기 |
| `connect()` / `disconnect()` | API 연결·해제 |

> **is_paper 처리**: Account의 `broker_config`에서 `is_paper` 값을 읽는다 (기본값: `True`, 모의투자). `is_paper`는 KIS 모의투자/실전투자 엔드포인트를 결정하는 브로커 내부 설정이며, Account의 `trading_mode`와 독립적이다. `trading_mode`는 시스템이 브로커 API를 호출할지 여부(VIRTUAL=가상거래, LIVE=실거래)를 결정하고, `is_paper`는 호출 시 어떤 KIS 서버로 요청할지를 결정한다.

### KIS API 특성 요약

| 항목 | 실전투자 | 모의투자 |
|------|----------|----------|
| REST Base URL | `https://openapi.koreainvestment.com:9443` | `https://openapivts.koreainvestment.com:29443` |
| WebSocket URL | `ws://ops.koreainvestment.com:31000` | `ws://ops.koreainvestment.com:21000` |
| Rate Limit | 분당 20회 | 초당 5회 |
| 인증 방식 | OAuth2 (`client_credentials` grant) | 동일 |
| 토큰 유효기간 | 24시간 | 동일 |
| 인증 엔드포인트 | `/oauth2/tokenP` | 동일 |
