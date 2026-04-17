# Rule Engine 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 타 모듈 설계 시 참고

- **Account 스펙**: RuleEngine은 계좌별 인스턴스로 동작하며, AccountService를 통해 계좌 상태 조회/변경
- **Bot 스펙**: OrderRequestEvent에 bot_id, account_id 포함 — 계좌별 이벤트 필터링 및 봇별 전략 룰 조회에 활용
- **Treasury 스펙**: RuleContext에서 계좌별 Treasury의 가용 예산(available) 조회
- **Trade 스펙**: RuleContext에서 TradeService의 포지션/성과 정보 조회 — 포지션은 Trade 모듈이 단일 소유자
- **Config 스펙**: DynamicConfigService로 룰 파라미터 런타임 변경
- **Web API 스펙**: 룰 관리 CRUD API 제공
