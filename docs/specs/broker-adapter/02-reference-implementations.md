# Broker Adapter 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 참고 구현체 분석

### 한국투자증권 Open API 구조

- REST API + 웹소켓 실시간 데이터
- OAuth2 인증 (접근 토큰 24시간 유효)
- 종목코드 표준화 (6자리)
- rate limit: 분당 20회 (실전), 초당 5회 (모의)

### FreqTrade의 거래소 추상화

- 표준화된 인터페이스
- ccxt 라이브러리 기반
- 동기/비동기 지원

### Ante Broker Adapter 설계 방향

Ante는 FreqTrade의 표준화된 인터페이스 방식을 채택하되, 한국 증권사 특성에 맞게 확장:

- **ABC 기반 인터페이스**: 증권사별 구현체 교체 용이
- **비동기 우선**: asyncio 기반 API 호출
- **실시간 스트리밍**: 웹소켓 기반 이벤트 발행
- **에러 처리 강화**: 증권사 API의 빈번한 장애 대응
- **한글 주석**: 한국 개발자 친화적
