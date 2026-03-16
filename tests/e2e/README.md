# E2E 테스트

## 사전 요구사항

```bash
pip install -e ".[e2e]"
playwright install chromium
```

## 실행 방법

### 1. Docker 환경 수동 기동 후 테스트

```bash
# 테스트 환경 기동
docker compose -f docker-compose.test.yml up --build -d

# API 테스트만 실행
pytest tests/e2e/ -m "e2e and not playwright" --base-url http://localhost:8000

# 대시보드 + API 전체 실행
pytest tests/e2e/ -m "e2e" --base-url http://localhost:8000

# 정리
docker compose -f docker-compose.test.yml down -v
```

### 2. Docker 자동 기동

```bash
pytest tests/e2e/ -m "e2e" --docker-up
```

## 테스트 구성

| 파일 | 내용 |
|------|------|
| `test_api_endpoints.py` | API 엔드포인트 응답 검증 |
| `test_dashboard_pages.py` | 대시보드 페이지 순회 (Playwright) |
| `test_full_scenario.py` | 봇→전략→주문→체결 전체 시나리오 |
