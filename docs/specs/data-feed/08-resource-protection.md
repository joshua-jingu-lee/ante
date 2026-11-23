# DataFeed 모듈 세부 설계 - 리소스 보호

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 리소스 보호

Ante와 같은 홈서버(인텔 N100, 4코어, TDP 6W)에서 구동된다.
수집 작업이 실시간 매매를 방해하지 않도록 두 가지 보호 장치를 둔다.

### 1. 시간대 제한 (Trading Window Guard)

장중(09:00~15:30 KST)에는 수집 작업을 실행하지 않는다.

- 가드는 각 실행이 확인한다(실행 모드별 동작의 정본: [07-execution-modes.md](07-execution-modes.md))
- `blocked_days`: 수집 대상 날짜의 요일이 해당하면 그 날짜를 건너뛴다(대기하지 않는다)
- `pause_during_trading = true`이고 현재 시각이 `blocked_hours` 내이면 backfill은 대기하고, daily는 그 실행을 건너뛴다. `blocked_hours`의 각 구간은 시작 ≤ 끝이어야 한다. 자정을 넘는 구간은 `23:00-23:59`와 `00:00-02:00`처럼 둘로 나눠 적는다(`ante feed start`가 시작할 때 거부한다)
- 설정으로 비활성화 가능 (`pause_during_trading = false`)

### 2. 프로세스 우선순위 (Nice)

OS 수준에서 프로세스의 CPU 우선순위를 낮춘다.

- 시작 시 `[general].nice_value`(0~19, 기본 10)를 프로세스 nice 값으로 설정한다(`os.setpriority`, 절대값 — 현재 값에 더하지 않는다). 설정에 실패하면 경고만 남기고 수집은 계속한다
- Ante 봇이 CPU를 필요로 할 때 자동으로 양보
- 동시 API 호출 수 제한 (concurrency cap)으로 네트워크 대역폭도 제어

### 3. 동시 실행 방지

`{data.path}/.feed/lock` 파일로 동시 실행을 방지한다.

- 시작 시 lock 파일에 PID 기록
- 이미 lock이 있으면 해당 PID 프로세스 존재 여부 확인
- 프로세스 존재 시 에러 메시지 출력 후 종료
- 프로세스 부재 시 (비정상 종료) lock 파일 제거 후 진행
