# DataFeed 모듈 세부 설계 - 장애 대응

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 장애 대응

### 재시도 전략

**Exponential Backoff + Full Jitter**

```
delay = random(0, min(cap, base * 2^attempt))
```

- 최대 재시도: 3~5회
- 초기 대기: 1~2초
- 최대 대기: 60초

**재시도 대상 분류:**

| 분류 | 조건 | 행동 |
|------|------|------|
| 재시도 가능 | HTTP 408, 429, 500, 502, 503, 504, 연결 타임아웃 | backoff 후 재시도 |
| 재시도 불가 | HTTP 400, 401, 403, 404, 422 | 즉시 스킵, 실패 로그 |
| 조건부 재시도 | HTTP 200이지만 body 파싱 실패, 빈 응답 | 1회 재시도 후 스킵 |
| API 레벨 에러 | data.go.kr `resultCode` ≠ `00`, DART `status` ≠ `000` | 에러 코드별 분기 (§각 소스 에러 코드 참조) |
| 수집 중단 | 일일 한도 초과 (data.go.kr 코드 22, DART 코드 020) | 체크포인트 저장 후 즉시 종료 |
| CRITICAL | 키 미등록/만료 (data.go.kr 30/31, DART 010/901) | 수집 전체 중단, CRITICAL 로그 |

### Rate Limiting

**Token Bucket 기반 제어** (DataFeed 자체 구현, APIGateway와 별도):

| API | 제한 | 설정 |
|-----|------|------|
| data.go.kr | 30 tps, 10,000건/일 | 토큰 충전: 25/초 (여유분 확보), 일일 카운터 |
| DART | 20,000건/일 | 일일 카운터, tps는 보수적으로 10/초 |

**일일 한도 추적**: 호출 수를 카운트하여 한도의 90% 도달 시 수집 중단, 다음 날 이어서.

### 데이터 검증 (4계층)

| 계층 | 검증 항목 | 실패 시 |
|------|---------|--------|
| 전송 | HTTP 상태 코드, Content-Length | 재시도 |
| 구문 | JSON 파싱, 인코딩 정상 | 재시도 → 스킵 |
| 스키마 | 필수 필드 존재, 타입 변환 가능 | 스킵 & 에러 로그 |
| 비즈니스 | low<=open/close<=high, volume>=0, 시계열 갭 | 경고 로그, 저장 |

### 중복 제거

- 자연키: `{symbol}:{timestamp}` (OHLCV), `{symbol}:{date}` (Fundamental)
- 수집 전: 체크포인트로 이미 수집한 날짜 건너뛰기
- 저장 시: `ParquetStore.write()`가 파티션 단위로 중복 제거
- data.go.kr 페이지네이션 경계에서 동일 레코드 중복 반환 가능 — 쓰기 전 DataFrame 내 `unique(subset=["timestamp", "symbol"])` 처리

### 날짜/시간 처리

| 항목 | 규칙 |
|------|------|
| API 요청 | KST 기준 `YYYYMMDD` 형식 |
| 내부 저장 | UTC |
| 변환 | `YYYYMMDD` (KST) → `YYYY-MM-DD 00:00:00 UTC` (일봉이므로 시각은 00:00) |
| 타임존 | `Asia/Seoul` (UTC+9, 서머타임 없음) |
