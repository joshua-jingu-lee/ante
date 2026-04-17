# DataFeed 모듈 세부 설계 - 체크포인트 및 리포트

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 체크포인트 및 리포트

### 체크포인트

수집 중단/재개를 위한 내부 상태. `{data}/.feed/checkpoints/`에 소스별로 저장.
**원자적 기록**: 임시 파일에 쓴 후 rename (write-then-rename).

```json
// checkpoints/data_go_kr_ohlcv.json
{
  "source": "data_go_kr",
  "data_type": "ohlcv",
  "last_date": "2024-06-15",
  "updated_at": "2026-03-17T01:23:45Z"
}
```

### 리포트

backfill/daily 실행 완료 시 생성되는 **운영 기록**.
`{data}/.feed/reports/{YYYY-MM-DD}-{mode}.json`에 저장.

```json
// reports/2026-03-17-daily.json
{
  "mode": "daily",
  "started_at": "2026-03-17T16:00:12Z",
  "finished_at": "2026-03-17T16:05:34Z",
  "duration_seconds": 322,
  "target_date": "2026-03-16",

  "summary": {
    "symbols_total": 2487,
    "symbols_success": 2485,
    "symbols_failed": 2,
    "rows_written": 2485,
    "data_types": ["ohlcv", "fundamental"]
  },

  "failures": [
    {
      "symbol": "003920",
      "date": "2026-03-16",
      "source": "data_go_kr",
      "reason": "HTTP 500 after 3 retries",
      "retries": 3
    }
  ],

  "warnings": [
    {
      "symbol": "005930",
      "date": "2026-03-16",
      "type": "business_rule",
      "message": "low > close (low=71200, close=71100)"
    }
  ],

  "config_errors": []
}
```

| 필드 | 설명 |
|------|------|
| `summary` | 수집 결과 요약 (종목 수, 성공/실패, 기록 행 수) |
| `failures` | 수집 실패 건 (종목, 날짜, 사유, 재시도 횟수) |
| `warnings` | 데이터 품질 경고 (비즈니스 규칙 위반, 시계열 갭 등) |
| `config_errors` | 설정 오류 (잘못된 routing, 누락된 API 키 등) |

### 로깅

stdout 출력, 디버깅 용도.

**레벨 기준:**

| 레벨 | 용도 |
|------|------|
| DEBUG | 개별 요청/응답 상세 (프로덕션 비활성화) |
| INFO | 수집 시작/완료, 체크포인트 갱신, 일별 통계 |
| WARNING | 재시도 발생, 비즈니스 검증 경고, 예상보다 적은 데이터 |
| ERROR | 최종 실패 (재시도 소진), 파싱 오류, 인증 실패 |
| CRITICAL | 전체 수집 중단 (일일 한도, 키 만료 등) |

**민감 정보**: API 키는 로그에 마스킹.
