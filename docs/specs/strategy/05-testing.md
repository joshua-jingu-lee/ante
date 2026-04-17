# Strategy 모듈 세부 설계 - 테스트 고려사항

> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 테스트 고려사항

- Strategy ABC를 상속한 클래스가 on_step을 구현하지 않으면 인스턴스화 불가 확인
- StrategyValidator: 문법 오류 파일 검증 → 에러 반환
- StrategyValidator: 금지 모듈 import 검증 → 에러 반환
- StrategyValidator: eval/exec/compile/__import__ 사용 검증 → 에러 반환
- StrategyValidator: open() 사용 검증 → 경고 반환
- StrategyValidator: 금지된 최상위 코드 검증 → 에러 반환
- StrategyValidator: Strategy 미상속 클래스 → 에러 반환
- StrategyValidator: meta, on_step 누락 → 각각 에러 반환
- StrategyLoader: 정상 파일 로드 → Strategy 하위 클래스 반환
- StrategyLoader: 다수 Strategy 클래스 → 에러 반환
- StrategyRegistry: 등록, 조회, 상태 변경 CRUD 정상 동작
- StrategyRegistry: 중복 strategy_id 등록 → 에러 반환
- StrategyContext: 데이터 조회, 포지션 조회 정상 동작
- Signal: frozen 확인, 필드 검증
- StrategyValidator: 유효하지 않은 exchange 값 → 에러 반환
- StrategyValidator: symbols와 exchange 불일치 → 경고 반환
- 봇 생성 시 KRX 전략 + KRX 계좌 → 허용
- 봇 생성 시 KRX 전략 + NYSE 계좌 → IncompatibleExchangeError
- 봇 생성 시 `"*"` 전략 + 모든 계좌 → 허용
