# Flow: 전략 조회

등록된 전략의 목록 확인, 필터링, 상세 정보 열람 흐름.

## Seed Data

- **전략 A** (registered): name="sma_cross", version="1.0", status=registered, bot_id=없음, cumulative_return=없음
  - params: { period_short: 5, period_long: 20 }
  - 거래 내역 없음
  - 성과 데이터 없음
- **전략 B** (active, 거래 없음): name="rsi_reversal", version="1.0", status=active, bot_id="bot_002", cumulative_return=0%
  - params: { rsi_period: 14, oversold: 30, overbought: 70 }
  - 거래 내역 없음
  - 성과 데이터 없음 (봇 시작 직후)
- **전략 C** (active, 거래 있음): name="momentum_v2", version="2.1", status=active, bot_id="bot_001", cumulative_return=+3.5%
  - params: { lookback: 14, threshold: 0.02 }
  - 거래 내역: 매수 2건, 매도 1건 (005930, 000660)
  - 성과: total_trades=3, win_rate=0.67, profit_factor=2.15, max_drawdown=0.018, realized_pnl=125000, sharpe_ratio=1.45
- **전략 D** (inactive): name="mean_revert", version="1.2", status=inactive, bot_id=없음, cumulative_return=-1.2%
  - params: { window: 30, z_score: 2.0 }
  - 거래 내역: 매수 3건, 매도 3건
  - 성과: total_trades=6, win_rate=0.33, profit_factor=0.78, max_drawdown=0.045, realized_pnl=-48000, sharpe_ratio=-0.32

---

## 1. 전략 목록 페이지 진입

1. 사이드바에서 "📈 전략과 성과" 클릭
2. **Expected**: `/strategies` 페이지로 이동
3. **Expected**: 헤더에 "전략과 성과" 타이틀 표시
4. **Expected**: 필터 버튼 4개 표시 — 전체, 운용중, 대기, 중지
5. **Expected**: "전체" 필터가 기본 선택 상태
6. **Expected**: 테이블에 4개 전략이 모두 표시

## 2. 전략 목록 테이블 내용 확인

1. 테이블 컬럼 확인
2. **Expected**: 5개 컬럼 — 전략명, 버전, 상태, 실행 봇, 누적 수익률
3. **Expected**: 전략 A 행
   - 전략명: "sma_cross", 버전: "1.0"
   - 상태 뱃지: "등록됨" (보라색/info)
   - 실행 봇: "-"
   - 누적 수익률: 표시 없음
4. **Expected**: 전략 B 행
   - 전략명: "rsi_reversal", 버전: "1.0"
   - 상태 뱃지: "활성" (파란색/positive)
   - 실행 봇: "bot_002"
   - 누적 수익률: "0.00%"
5. **Expected**: 전략 C 행
   - 전략명: "momentum_v2", 버전: "2.1"
   - 상태 뱃지: "활성" (파란색/positive)
   - 실행 봇: "bot_001"
   - 누적 수익률: "+3.50%" (파란색/positive)
6. **Expected**: 전략 D 행
   - 전략명: "mean_revert", 버전: "1.2"
   - 상태 뱃지: "비활성" (회색/muted)
   - 실행 봇: "-"
   - 누적 수익률: "-1.20%" (빨간색)

## 3. 필터 — 운용중

1. "운용중" 필터 버튼 클릭
2. **Expected**: 전략 B, C 표시 (2건)
3. **Expected**: 전략 A, D는 표시되지 않음

## 4. 필터 — 대기

1. "대기" 필터 버튼 클릭
2. **Expected**: 전략 A만 표시 (1건)

## 5. 필터 — 중지

1. "중지" 필터 버튼 클릭
2. **Expected**: 전략 D만 표시 (1건)

## 6. 필터 — 전체로 복원

1. "전체" 필터 버튼 클릭
2. **Expected**: 4개 전략 모두 표시

## 7. 필터 — 빈 결과

- Seed Data 변경: active 상태 전략 없음 (전략 B, C를 inactive로 변경)

1. "운용중" 필터 버튼 클릭
2. **Expected**: "등록된 전략이 없습니다" 빈 상태 메시지 표시

## 8. 전략 상세 — registered 전략 (전략 A)

1. 전략 목록에서 "sma_cross" 행 클릭
2. **Expected**: `/strategies/{id}` 상세 페이지로 이동
3. **Expected**: 헤더에 전략명 "sma_cross" 표시
4. **Expected**: 버전 "v1.0", 상태 뱃지 "등록됨" 표시
5. **Expected**: 실행 봇 링크 미표시 (bot_id 없음)

## 9. 전략 상세 — 성과 데이터 없는 경우

1. 전략 A 상세 페이지에서 "성과 지표" 섹션 확인
2. **Expected**: 지표 카드 미표시, "아직 성과 데이터가 없습니다" 메시지 표시
3. **Expected**: 자산 추이 차트도 빈 상태 메시지 표시
4. **Expected**: 거래 내역 탭 진입 시 "거래 내역이 없습니다" 메시지 표시

## 10. 전략 상세 — 파라미터 탭

1. "파라미터" 탭이 기본 선택 상태 확인
2. **Expected**: 전략 파라미터가 키-값 형식으로 표시
   - period_short: 5
   - period_long: 20

## 11. 전략 상세 — 거래 내역 탭 (빈 상태)

1. "거래 내역" 탭 클릭
2. **Expected**: "거래 내역이 없습니다" 빈 상태 메시지 표시

## 12. 전략 상세 — active이지만 거래 없는 전략 (전략 B)

1. 뒤로가기 → 전략 목록에서 "rsi_reversal" 행 클릭
2. **Expected**: 전략명 "rsi_reversal", 버전 "v1.0", 상태 "활성" 표시
3. **Expected**: 실행 봇 "bot_002" 링크 표시
4. **Expected**: 성과 지표 섹션에 "아직 성과 데이터가 없습니다" 메시지 표시
5. **Expected**: 파라미터 탭에 rsi_period: 14, oversold: 30, overbought: 70 표시
6. **Expected**: 거래 내역 탭에 "거래 내역이 없습니다" 메시지 표시

## 13. 전략 상세 — active 전략 (전략 C)

1. 뒤로가기 → 전략 목록에서 "momentum_v2" 행 클릭
2. **Expected**: 전략명 "momentum_v2", 버전 "v2.1", 상태 "활성" 표시
3. **Expected**: 실행 봇 "bot_001" 링크 표시 (파란색, `/bots/bot_001`으로 연결)

## 14. 전략 상세 — 성과 지표 (데이터 있음)

1. 전략 C 상세 페이지에서 "성과 지표" 섹션 확인
2. **Expected**: 각 지표 카드에 값 표시
   - 총 거래 수: 3
   - 승률: 67.00%
   - 수익 팩터: 2.15
   - 최대 낙폭: 1.80%
   - 실현 손익: 125,000원
   - 샤프 비율: 1.45

## 15. 전략 상세 — 거래 내역 탭 (데이터 있음)

1. "거래 내역" 탭 클릭
2. **Expected**: 테이블에 3건의 거래 표시
3. **Expected**: 각 행에 종목, 방향(매수/매도 뱃지), 수량, 가격, 손익, 체결일 표시
4. **Expected**: 매수 → 파란색 "매수" 뱃지, 매도 → 빨간색 "매도" 뱃지
5. **Expected**: 손익이 양수이면 파란색, 음수이면 빨간색

## 16. 전략 상세 — inactive 전략 (전략 D)

1. 뒤로가기 → 전략 목록에서 "mean_revert" 행 클릭
2. **Expected**: 상태 뱃지 "비활성" (회색) 표시
3. **Expected**: 실행 봇 링크 미표시
4. **Expected**: 성과 지표에 부정적 수치 표시
   - 실현 손익: -48,000원 (빨간색)
   - 샤프 비율: -0.32

## 17. 자산 추이 차트 영역

1. 전략 C 상세 페이지에서 "자산 추이" 섹션 확인
2. **Expected**: 차트 영역이 표시됨 (현재 플레이스홀더: "📈 에쿼티 커브")
