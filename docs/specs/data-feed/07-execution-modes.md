# DataFeed 모듈 세부 설계 - 실행 모드

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 실행 모드

### `ante feed start` — 내장 스케줄러 (상주 프로세스)

설정의 `[schedule]`에 따라 backfill과 daily를 자동 실행하는 상주 프로세스.
systemd 서비스로 바로 사용할 수 있어 OS별 스케줄러 설정이 불필요하다.

```
ante feed start
  │
  ├─ config 로드 ({data}/.feed/config.toml + .env + 환경변수)
  │
  ├─ [스케줄 루프]
  │   ├─ backfill 미완료? → backfill_at 시각에 backfill 실행
  │   ├─ daily_at 시각 도달? → daily 실행
  │   └─ 방어 가드 (blocked_days/blocked_hours 해당 시 대기)
  │
  └─ 종료 시그널(SIGTERM) 수신 시 체크포인트 저장 후 안전 종료
```

### `ante feed run backfill` / `ante feed run daily` — one-shot 실행

외부 스케줄러(cron 등)를 사용하거나 수동 실행할 때 사용. 1회 실행 후 종료.

### Backfill — 과거 데이터 대량 수집

`backfill_since` 이후의 과거 데이터를 API 일일 한도 내에서 수집한다.

```
ante feed run backfill
  │
  ├─ config 로드 ({data}/.feed/config.toml + .env + 환경변수)
  ├─ 체크포인트 로드 ({data}/.feed/checkpoints/)
  ├─ 날짜 범위 결정 (체크포인트 이후 ~ 오늘)
  │
  ├─ [날짜별 루프]
  │   ├─ 방어 가드 (blocked_days/blocked_hours) → 해당 시 대기
  │   ├─ 일일 한도 확인 → 도달 시 체크포인트 저장 후 종료
  │   │
  │   ├─ Extract: API 호출 (전종목 조회, 페이지네이션)
  │   │   └─ 실패 시 재시도 → 최종 실패 시 스킵 & 로그
  │   ├─ Transform: ante.data.normalizer로 정규화 + validate.py로 검증
  │   ├─ Load: ante.data.store.ParquetStore.write()로 저장
  │   └─ 체크포인트 갱신
  │
  └─ 리포트 생성 ({data}/.feed/reports/)
```

### Daily Incremental — 일일 증분 수집

Backfill 완료 후, 매일 전일 데이터를 보강한다.

```
ante feed run daily
  │
  ├─ config 로드 ({data}/.feed/config.toml + .env + 환경변수)
  ├─ 전일 날짜 결정
  ├─ 방어 가드 (blocked_days/blocked_hours)
  ├─ 동일 ETL 흐름 (날짜 1개)
  └─ 리포트 생성
```
