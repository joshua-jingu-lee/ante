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
BOOTSTRAP_OUTPUT=$(printf '%s\n%s\n' "$QA_PASSWORD" "$QA_PASSWORD" | \
    ante member bootstrap --id qa-admin --name "QA Admin" 2>/dev/null || true)
QA_TOKEN=$(echo "$BOOTSTRAP_OUTPUT" | grep -oE 'ante_[a-z]+_[A-Za-z0-9_-]+' | head -1)

if [ -z "$QA_TOKEN" ]; then
    # 이미 bootstrap 완료된 경우 (재기동) — 로그인 후 rotate-token으로 재발급
    echo "[qa] 기존 master 계정 감지 — 토큰 재발급 중..."
    LOGIN_RESP=$(curl -sf -X POST http://localhost:8000/api/auth/login \
        -H "Content-Type: application/json" \
        -d "{\"member_id\":\"qa-admin\",\"password\":\"$QA_PASSWORD\"}" \
        -c - 2>/dev/null || true)
    SESSION_COOKIE=$(echo "$LOGIN_RESP" | grep 'ante_session' | awk '{print $NF}')
    if [ -n "$SESSION_COOKIE" ]; then
        ROTATE_RESP=$(curl -sf -X POST http://localhost:8000/api/members/qa-admin/rotate-token \
            -b "ante_session=$SESSION_COOKIE" 2>/dev/null || true)
        QA_TOKEN=$(echo "$ROTATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || true)
    fi
fi

if [ -n "$QA_TOKEN" ]; then
    export ANTE_MEMBER_TOKEN="$QA_TOKEN"
    echo "export ANTE_MEMBER_TOKEN=\"$QA_TOKEN\"" >> /root/.bashrc
    echo "[qa] ANTE_MEMBER_TOKEN 설정 완료"
else
    echo "[qa] WARNING: ANTE_MEMBER_TOKEN 설정 실패" >&2
fi

echo "[qa] QA 시드 계좌 확인 (Treasury 초기화 보장)..."
# 계좌가 없으면 API로 테스트 계좌 생성 → 서버 재기동하여 Treasury 초기화
ACCOUNT_COUNT=$(curl -sf http://localhost:8000/api/accounts | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('accounts',[])))" 2>/dev/null || echo "0")
if [ "$ACCOUNT_COUNT" = "0" ]; then
    echo "[qa] 계좌 없음 — 시드 계좌 생성 중..."
    curl -sf -X POST http://localhost:8000/api/accounts \
        -H "Content-Type: application/json" \
        -d '{"account_id":"test","name":"QA Test","broker_type":"test","trading_mode":"virtual"}' \
        > /dev/null 2>&1 || true

    # 계좌 생성 후 서버 재기동하여 Treasury 초기화
    echo "[qa] 서버 재기동 (Treasury 초기화)..."
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true

    python -m ante.main &
    SERVER_PID=$!

    for i in $(seq 1 30); do
        if python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/system/health')" 2>/dev/null; then
            echo "[qa] 서버 재기동 완료 (${i}초)"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "[qa] 서버 재기동 헬스체크 타임아웃" >&2
            exit 1
        fi
        sleep 1
    done
else
    echo "[qa] 계좌 ${ACCOUNT_COUNT}개 확인됨 — 시드 생략"
fi

echo "[qa] QA 전략 레지스트리 시딩..."
python scripts/qa_seed_strategies.py --strategies-dir strategies --db-path db/ante.db

echo "[qa] QA 테스트용 동적 설정 시드 등록..."
sqlite3 db/ante.db "INSERT OR IGNORE INTO dynamic_config (key, value, category, updated_at) VALUES ('risk.test_qa_key', '0', 'risk', datetime('now'));"

echo "[qa] 엔트리포인트 초기화 완료"

# 서버 포그라운드 전환
wait $SERVER_PID
