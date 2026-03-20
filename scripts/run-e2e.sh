#!/bin/bash
# E2E 테스트 원커맨드 실행 스크립트
#
# 사용법:
#   ./scripts/run-e2e.sh                          # 전체 실행
#   ./scripts/run-e2e.sh test_flow_login_dashboard # 특정 플로우만
set -e

COMPOSE_FILE="docker-compose.test.yml"
FLOW="${1:-}"

echo "[e2e] Docker 이미지 빌드 및 테스트 환경 기동..."

if [ -n "$FLOW" ]; then
    echo "[e2e] 특정 플로우 실행: $FLOW"
    docker compose -f "$COMPOSE_FILE" up --build -d ante-test
    docker compose -f "$COMPOSE_FILE" run --rm e2e-runner \
        pytest "tests/e2e/${FLOW}.py" -m e2e -v --tb=short \
        --base-url http://ante-test:3982 \
        --output=test-results \
        --junit-xml=test-results/e2e-results.xml
else
    echo "[e2e] 전체 E2E 테스트 실행..."
    docker compose -f "$COMPOSE_FILE" up --build \
        --abort-on-container-exit \
        --exit-code-from e2e-runner
fi

EXIT_CODE=$?

echo "[e2e] 테스트 환경 정리..."
docker compose -f "$COMPOSE_FILE" down -v

if [ $EXIT_CODE -eq 0 ]; then
    echo "[e2e] 테스트 완료 (성공). 결과: test-results/"
else
    echo "[e2e] 테스트 완료 (실패). 결과: test-results/"
fi

exit $EXIT_CODE
