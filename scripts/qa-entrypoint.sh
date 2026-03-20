#!/bin/bash
# QA 테스트 환경 엔트리포인트
# 1. 서버 시작 (백그라운드)
# 2. 헬스체크 대기
# 3. 초기 멤버 부트스트랩
# 4. 서버 포그라운드 전환
set -e

echo "[qa] Ante 서버 시작..."
python -m ante.main &
SERVER_PID=$!

# 헬스체크 대기 (최대 30초)
echo "[qa] 헬스체크 대기 중..."
for i in $(seq 1 30); do
    if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/system/health')" 2>/dev/null; then
        echo "[qa] 서버 준비 완료"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[qa] 서버 시작 타임아웃 (30초)"
        exit 1
    fi
    sleep 1
done

# 초기 멤버 부트스트랩 (QA 인증용)
echo "[qa] 멤버 부트스트랩..."
ante member bootstrap --name "QA Admin" --org default 2>/dev/null || true

echo "[qa] QA 서버 준비 완료"

# 서버 포그라운드 전환
wait $SERVER_PID
