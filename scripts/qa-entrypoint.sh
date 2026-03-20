#!/bin/bash
# QA 테스트 환경 엔트리포인트
# 1. Ante 서버 백그라운드 기동
# 2. 헬스체크 대기 (최대 30초)
# 3. QA Admin 멤버 부트스트랩
# 4. 서버 포그라운드 전환
set -e

echo "[qa] Ante 서버 시작 (백그라운드)..."
python -m ante.main &
SERVER_PID=$!

echo "[qa] 헬스체크 대기 (최대 30초)..."
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/system/health')" 2>/dev/null; then
        echo "[qa] 서버 준비 완료 (${i}초)"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[qa] 서버 헬스체크 타임아웃 (30초)" >&2
        exit 1
    fi
    sleep 1
done

echo "[qa] QA Admin 멤버 부트스트랩..."
# bootstrap은 대화형 패스워드 프롬프트를 사용하므로
# confirmation_prompt=True → 패스워드를 2번 입력해야 한다
QA_PASSWORD="${QA_ADMIN_PASSWORD:-qaadmin123!}"
printf '%s\n%s\n' "$QA_PASSWORD" "$QA_PASSWORD" | \
    ante member bootstrap --id qa-admin --name "QA Admin" 2>/dev/null || true

echo "[qa] 엔트리포인트 초기화 완료"

# 서버 포그라운드 전환
wait $SERVER_PID
