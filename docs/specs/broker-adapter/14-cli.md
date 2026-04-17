# Broker Adapter 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# CLI 인터페이스

증권사 연동 테스트용 CLI 명령:

```bash
# 잔고 조회
ante broker balance

# 포지션 조회
ante broker positions

# 현재가 조회
ante broker price <symbol>

# 주문 접수 테스트
ante broker order --symbol 005930 --side buy --quantity 1 --type market

# 실시간 가격 모니터링
ante broker stream prices --symbols 005930,000660

# 연결 상태 확인
ante broker health
```
