# Bot 모듈 세부 설계 - 테스트 고려사항

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 테스트 고려사항

- Bot 생성 시 전략 로드 및 StrategyContext 주입 정상 동작
- start() → on_start() 호출 + BotStartedEvent 발행 확인
- _run_loop()에서 on_step() 호출 → Signal 반환 → OrderRequestEvent 변환 확인
- _run_loop() 매 사이클 완료 시 BotStepCompletedEvent 발행 확인 (result="success", signal_count, duration_ms)
- on_step 타임아웃 시 BotStepCompletedEvent(result="timeout") 발행 확인
- 시그널 수 초과 시 BotStepCompletedEvent(result="signal_overflow") 발행 확인
- 예외 발생 시 BotStepCompletedEvent(result="error") 발행 확인
- 빈 Signal 리스트 반환 시 OrderRequestEvent 미발행 확인 (BotStepCompletedEvent는 발행)
- 예외 발생 시 해당 봇만 ERROR, 다른 봇 영향 없음 확인
- stop() → Task 취소 + on_stop() 호출 + BotStoppedEvent 발행 확인
- OrderFilledEvent 수신 → 해당 bot_id만 on_fill() 호출 확인
- VIRTUAL 계좌 봇: PaperPortfolioView 가상 자금 관리 정상 동작
- BotManager: 복수 봇 동시 운영 + 개별 시작/중지 확인
- BotManager: 봇 생성 시 Account 존재·상태 검증 확인
- BotManager: Strategy.meta.exchange와 Account.exchange 불일치 시 에러 확인
- BotManager: AccountSuspendedEvent 수신 시 해당 계좌 봇만 중지 확인
- on_order_update(): 주문 상태 변경 이벤트 수신 → 전략의 on_order_update() 호출 확인
- on_order_update(): OrderCancelFailedEvent 처리 시 status="cancel_failed" 전달 확인
- 시그널 키: accepts_external_signals=True 전략의 봇 생성 시 키 발급 확인
- 시그널 키: accepts_external_signals=False 전략의 봇 생성 시 키 미발급 확인
- 시그널 키: rotate 시 기존 키 무효화 + 새 키 발급 확인
- 시그널 채널: 유효한 키로 connect 시 양방향 스트림 수립 확인
- 시그널 채널: 무효한 키로 connect 시 거부 확인
- 시그널 채널: signal 메시지 수신 → ExternalSignalEvent 발행 → on_data() 호출 확인
- 시그널 채널: query 메시지 수신 → StrategyContext 경유 조회 → 결과 반환 확인
- 시그널 채널: 체결/상태 변경 → 채널을 통해 외부에 통보 확인
