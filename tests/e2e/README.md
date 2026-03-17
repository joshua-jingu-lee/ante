# E2E 테스트

## 아키텍처

Docker 2-container 모델로 실행된다:
- **ante-test**: Ante 서버 (시드 데이터 + Mock Broker)
- **e2e-runner**: Playwright + pytest (Chromium 내장)

호스트에 별도 설치가 필요 없다.

## 실행 방법

### 원커맨드 전체 실행

```bash
./scripts/run-e2e.sh
```

### 특정 플로우만 실행

```bash
./scripts/run-e2e.sh test_flow_login_dashboard
```

### Docker Compose 직접 실행

```bash
# 전체 실행 (빌드 포함)
docker compose -f docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from e2e-runner

# 정리
docker compose -f docker-compose.test.yml down -v
```

### 로컬 개발 (호스트에서 직접 실행)

```bash
pip install -e ".[e2e]"
playwright install chromium

# ante-test 컨테이너를 먼저 기동
docker compose -f docker-compose.test.yml up --build -d ante-test

# 호스트에서 테스트 실행
pytest tests/e2e/ -m e2e --base-url http://localhost:8000 -v

# 정리
docker compose -f docker-compose.test.yml down -v
```

## 테스트 결과

```
test-results/
  e2e-results.xml    # JUnit XML 리포트
  *.png              # 실패 시 자동 스크린샷
```

## 테스트 구성

### 플로우 테스트 (시나리오별)

| 파일 | 시나리오 | 스펙 |
|------|----------|------|
| `test_flow_login_dashboard.py` | `login-dashboard` | 로그인 → 대시보드 |
| `test_flow_bot_management.py` | `bot-management` | 봇 CRUD + 상세 |
| `test_flow_strategy_browse.py` | `strategy-browse` | 전략 목록 + 상세 |
| `test_flow_treasury.py` | `treasury` | 자금 관리 |
| `test_flow_member_management.py` | `member-management` | 멤버/에이전트 관리 |
| `test_flow_approvals.py` | `approvals` | 결재함 |
| `test_flow_backtest_data.py` | `backtest-data` | 백테스트 데이터 |
| `test_flow_settings.py` | `settings` | 설정 |

### 레거시 테스트

| 파일 | 내용 |
|------|------|
| `test_api_endpoints.py` | API 엔드포인트 응답 검증 |
| `test_dashboard_pages.py` | 페이지 렌더링 검증 |
| `test_full_scenario.py` | 매매 파이프라인 시나리오 |
| `test_visual_verification.py` | 시각적 검증 |

## 시드 데이터

각 플로우 테스트는 모듈 상단에 `SCENARIO` 변수를 선언한다.
테스트 실행 시 `POST /api/test/reset?scenario={name}` 으로 DB를 리셋한다.

시드 SQL 파일: `tests/fixtures/seed/scenarios/`
- `_base.sql` — 공통 (시스템 상태, owner 멤버)
- `{scenario}.sql` — 시나리오별 데이터

### 새 시나리오 추가 방법

1. `tests/e2e/specs/` 에 스펙 문서 작성
2. `tests/fixtures/seed/scenarios/{name}.sql` 에 시드 SQL 작성
3. `tests/e2e/test_flow_{name}.py` 에 테스트 파일 작성 (SCENARIO = "{name}")
