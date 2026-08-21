# DataFeed 모듈 세부 설계 - 체크포인트 및 리포트

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 체크포인트 및 리포트

### 체크포인트

수집 중단/재개를 위한 내부 상태. `{data.path}/.feed/checkpoints/`에 소스별로 저장.
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
`{data.path}/.feed/reports/{YYYY-MM-DDTHHMMSS}-{mode}.json`에 저장.
타임스탬프는 `started_at`의 초까지(콜론 제거)이며, 같은 날 같은 mode를 다시
실행해도 서로 다른 파일명을 얻어 기존 이력을 덮어쓰지 않는다(#2123). 같은 초의
`started_at`으로 재실행되어 파일명이 충돌하면 `-1`, `-2` ... suffix를 붙여 보존한다.

```json
// reports/2026-03-17T160012-daily.json
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
    "failures_total": 2,
    "warnings_total": 2,
    "warnings_by_type": { "business_rule": 1, "untyped": 1 },
    "warnings_truncated": false,
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
    },
    {
      "source": "dart",
      "year": "2025",
      "reprt_code": "11011",
      "message": "재무제표 응답 없음"
    }
  ],

  "config_errors": []
}
```

`warnings` 배열은 **전수가 아니라 `type` 버킷별 유계 샘플**이다(아래
"경고 유계화" 참조). 두 번째 예시처럼 `type` 키가 없는 경고는 `untyped`
버킷으로 집계된다 — `summary.warnings_by_type`에는 `null` 키가 등장하지 않는다.

| 필드 | 설명 |
|------|------|
| `summary` | 수집 결과 요약 (종목 수, 성공/실패, 총 실패 건수, 총 경고 건수, 기록 행 수) |
| `summary.failures_total` | 총 실패 건수(`len(failures)`). `symbols_failed`는 종목 단위 실패만 세지만, `failures`에는 날짜/소스 단위 실패(예: data.go.kr 특정 날짜 실패, DART 소스 실패)가 종목에 귀속되지 않은 채 포함될 수 있다. 따라서 `symbols_failed=0`이어도 `failures_total>0`일 수 있으며, 상세는 `failures` 배열을 참조한다. |
| `summary.warnings_total` | **전수 정확** 총 경고 건수. `warnings` 배열은 유계 절단되므로 `len(warnings)`는 총계가 아니다 — 총 건수는 반드시 이 필드로 보고한다. |
| `summary.warnings_by_type` | 경고 `type` 버킷별 **전수 정확** 건수(`{버킷: 건수}`). 버킷명 오름차순으로 직렬화한다(삽입 순서 = 경고 도착 순서라 실행마다 달라지므로). `type` 키가 없는 경고는 `untyped` 버킷으로 집계한다. |
| `summary.warnings_truncated` | `warnings` 배열이 버킷 상한으로 절단되었는지 여부(`bool`). `true`면 절단된 상세는 로그를 참조한다. |
| `failures` | 수집 실패 건. 종목 단위(종목, 날짜, 사유, 재시도 횟수)뿐 아니라 종목에 귀속되지 않는 날짜/소스 단위 실패도 포함한다. |
| `warnings` | 데이터 품질 경고 **샘플** (비즈니스 규칙 위반, 시계열 갭 등). `type` 버킷별 최대 1,000건까지만 보존한다(아래 "경고 유계화"). |
| `config_errors` | 설정 오류 (잘못된 routing, 누락된 API 키 등) |

#### 경고 유계화 (bounded warnings)

리포트 `warnings` 배열은 **실행 전체 누적이 아니라 `type` 버킷별로 유계 절단된
샘플**이다. 다년 범위 backfill이 행 단위 경고를 상한 없이 메모리에 누적해
프로세스 메모리를 소진시켰기 때문이다(#2414).

- **절단은 적재 시점에 한다.** 리포트 생성 시점에 자르면 인메모리 누적이 그대로
  남아 목적을 달성하지 못한다.
- **보존 상한은 `type` 버킷당 1,000건**이다. 이 값은 코드 모듈 상수이며 설정
  노출 대상이 아니다. 경고 메모리는 `버킷 수 × 1,000`으로 **날짜 범위와 무관하게
  유계**다.
- **집계는 절단과 무관하게 전수 정확하다.** `summary.warnings_total` /
  `summary.warnings_by_type`은 절단된 건수까지 포함한 정확한 값이며, 절단 발생
  자체는 `summary.warnings_truncated`로 표면화한다.
- **절단분 상세는 로그에서 회수한다.** 경고는 발생 시점에 전건 로깅되므로
  "규모는 리포트, 상세는 로그"로 역할이 분리된다.
- **소비자는 총 건수를 `summary.warnings_total`로 읽는다.** `len(warnings)`로
  총계를 계산하면 절단 시 축소 보고가 된다. 해당 필드가 없는 구버전 리포트에
  한해 `len(warnings)` 폴백을 허용한다.
- daily 리포트도 같은 규칙을 따른다. 통상 단일 일자 물량은 상한 미만이라 절단이
  발생하지 않지만, 전 종목 이상치 일자처럼 통상 물량을 크게 넘는 날은 daily도
  절단되며 그 사실이 `warnings_truncated`로 드러난다.

**경고 `type`은 유계 정적 집합이다 (규범).** 위 메모리 상한은 버킷 수가
유계라는 전제 위에 성립한다. 따라서 경고 생산자는 **정적 리터럴 `type`만**
사용하며, 종목·날짜·경로·메시지 등 런타임 값으로 `type`을 **동적 조립하는 것을
금지**한다(동적 `type`은 버킷 수를 무한히 늘려 상한을 무효화한다). 현재 집합:

| `type` | 의미 |
|--------|------|
| `store_merge` | 파티션 merge 실패 → 기존 파일 보존(checkpoint 전진 게이트) |
| `store_recovered` | 0바이트 파티션 자동복구(비게이트) |
| `derived_indicators` | 파생 지표 계산 실패 |
| `empty_corp_code_map` | DART corp_code 매핑이 비어 있음 |
| `invalid_symbol` | 종목 코드 형식 위반 |
| `schema_validation` | 스키마 검증 위반 |
| `business_rule` | 비즈니스 규칙 위반 |
| `untyped` | `type` 키가 없는 경고의 정규화 버킷 |

`untyped`는 적재 시점의 **정규화 결과**이지 생산자가 직접 기록하는 값이 아니다.
신규 경고 `type`을 도입할 때는 이 표를 함께 갱신한다.

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
