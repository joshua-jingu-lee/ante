#!/bin/bash
# QA 테스트 환경 엔트리포인트
# 1. ante init으로 QA Admin 마스터 부트스트랩 (서버 기동 전; DB 파일을 서버가 만들기 전에 실행)
# 2. reset-password로 QA 고정 패스워드 동기화 (신규 DB만) — init 토큰은 여기서 무효화됨
# 3. Ante 서버 백그라운드 기동
# 4. 헬스체크 대기 (최대 30초)
# 5. login + rotate-token으로 유효 토큰을 항상 재발급
# 6. 서버 포그라운드 전환
set -e

# config/system.qa.toml 의 [db].path=/app/db/ante.db 와 CLI 의 get_db_path 가
# 같은 DB 를 바라보도록 ANTE_CONFIG_DIR 을 /app 으로 고정한다. 이 값이 없으면
# get_db_path 가 ~/.config/ante/db/ante.db 폴백을 사용해 QA 서버 DB 와
# 다른 DB 를 보게 된다 (Codex 10차 review Finding 1).
#
# 이 export 는 현재 스크립트에서 실행되는 모든 ante CLI 호출(`ante init`,
# `ante member reset-password`, `ante --format json ...` 등)에 적용된다.
# ante init 의 `--dir /app` 옵션과 독립적으로 작동하지만, member reset-password
# 처럼 `--config-dir` 옵션을 받지 않는 서브커맨드는 env var 에만 의존한다.
export ANTE_CONFIG_DIR=/app

echo "[qa] QA Admin 멤버 부트스트랩 (ante init 통합, issue #1125)..."
# ante init은 비대화형. 신규 DB일 때만 master를 생성하고 JSON에 recovery_key를 반환한다.
# QA TC(tests/tc/)와 docker-compose.qa.yml의 QA_ADMIN_PASSWORD 계약을 지키기 위해
# init 직후 reset-password로 DB의 master 비밀번호를 $QA_PASSWORD 로 동기화한다.
# --dir /app: 서버(config/system.qa.toml) [db].path=/app/db/ante.db 와 init DB 경로 일치
#
# 주의 1: ante init과 ante member reset-password는 반드시 서버 기동 전에 실행해야 한다.
# 서버(src/ante/main.py _init_account)가 먼저 기동되면 DB 파일을 자동 생성해 버려
# ante init의 master bootstrap이 db_existed_before=True 분기로 항상 skip된다.
#
# 주의 2: init이 반환한 토큰은 사용하지 않는다. 아래 reset-password 호출이
# recovery_key_manager._invalidate_token으로 기존 토큰을 무효화하기 때문이다.
# 유효한 토큰은 서버 기동 후 login + rotate-token 경로로만 발급한다.
QA_PASSWORD="${QA_ADMIN_PASSWORD:-qaadmin123!}"
#
# init 호출 — stdout/stderr를 분리 캡처해 partial-failure 복구 이벤트를 보존한다.
# * 성공 (exit=0): stdout JSON payload에 recovery_key 포함.
# * test account 단계만 실패: stdout은 에러 payload, stderr에 master_bootstrap_complete
#   JSON 이벤트가 1줄 나오므로 이 stderr에서 recovery_key 복구.
# * 이미 초기화(code=already_initialized): 재기동 시나리오로 간주하고 login+rotate
#   경로로 계속 진행한다.
# * 그 외 복구 불가능한 실패(code=test_account_inactive / bootstrap_failed / ...):
#   stdout/stderr를 남기고 즉시 exit 1 해 깨진 상태로 서버가 기동되는 것을 막는다.
#
# 과거 구현은 `2>/dev/null || true`로 stderr과 exit code를 모두 버려 partial-failure
# 시 recovery_key가 영구 소실되는 회귀가 있었다 (Codex 6차 review Finding 2).
# 또한 non-zero exit을 모두 "기존 상태 = 재기동"으로 오인하던 회귀는
# Codex 7차 review에서 잡혔다 — 현재는 stdout JSON의 code 필드를 분기 기준으로 쓴다.
INIT_STDOUT=$(mktemp)
INIT_STDERR=$(mktemp)
trap 'rm -f "$INIT_STDOUT" "$INIT_STDERR"' EXIT

INIT_EXIT=0
ante --format json init --dir /app --member-id qa-admin --name "QA Admin" \
    > "$INIT_STDOUT" 2> "$INIT_STDERR" || INIT_EXIT=$?

INIT_JSON=""
INIT_RECOVERY_KEY=""
if [ "$INIT_EXIT" -eq 0 ]; then
    # 정상 성공 경로: stdout payload에서 recovery_key 추출
    INIT_JSON=$(cat "$INIT_STDOUT")
    INIT_RECOVERY_KEY=$(printf '%s' "$INIT_JSON" | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('recovery_key',''))" \
        2>/dev/null || true)
elif grep -q 'master_bootstrap_complete' "$INIT_STDERR"; then
    # Partial-failure 경로: master는 생성됐지만 test account 생성이 실패.
    # stderr 1줄 JSON 이벤트에서 recovery_key/password 복구.
    EVENT_LINE=$(grep 'master_bootstrap_complete' "$INIT_STDERR" | head -1)
    INIT_RECOVERY_KEY=$(printf '%s' "$EVENT_LINE" | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('recovery_key',''))" \
        2>/dev/null || true)
    echo "[qa] ante init test account 단계 실패 — master는 생성됨. stderr에서 recovery key 복구." >&2
    echo "[qa] init stderr:" >&2
    cat "$INIT_STDERR" >&2
else
    # master_bootstrap_complete 이벤트도 없는 실패 — stdout JSON의 code 필드로
    # 실패 유형을 구분한다. OutputFormatter.error가 JSON 모드에서
    # `{"error":..., "code":...}`를 stdout으로 내보내고 exit 1 한다.
    # * already_initialized: 기존 DB로 이어가는 재기동 시나리오 → 계속 진행
    # * test_account_inactive / bootstrap_failed / test_account_failed / 기타:
    #   복구 불가능한 치명적 실패 → 즉시 exit 1 하여 깨진 상태로 서버가 기동되는
    #   것을 막는다.
    INIT_CODE=$(python3 -c "
import json, sys
try:
    with open('$INIT_STDOUT') as f:
        print(json.load(f).get('code', ''))
except Exception:
    print('')
" 2>/dev/null || true)

    if [ "$INIT_CODE" = "already_initialized" ]; then
        echo "[qa] ante init 이미 완료된 상태 — 기존 DB로 재기동 진행" >&2
    else
        echo "[qa] FATAL: ante init 실패 (code='$INIT_CODE', exit=$INIT_EXIT)" >&2
        echo "[qa] init stdout:" >&2
        cat "$INIT_STDOUT" >&2
        if [ -s "$INIT_STDERR" ]; then
            echo "[qa] init stderr:" >&2
            cat "$INIT_STDERR" >&2
        fi
        exit 1
    fi
fi

# init 임시 파일 정리 후 trap 해제 (이후 COOKIE_JAR trap이 덮어쓴다).
rm -f "$INIT_STDOUT" "$INIT_STDERR"
trap - EXIT

# init이 새 master를 발급한 경우(=신규 DB 또는 partial-failure 복구)에만 QA
# 고정 패스워드로 동기화한다. 재기동(기존 DB) 시에는 INIT_RECOVERY_KEY가 비어
# 있으므로 이 블록이 자동으로 skip 된다.
if [ -n "$INIT_RECOVERY_KEY" ]; then
    echo "[qa] QA 고정 패스워드로 master 비밀번호 동기화..."
    if printf '%s\n%s\n' "$QA_PASSWORD" "$QA_PASSWORD" | \
        ante member reset-password --recovery-key "$INIT_RECOVERY_KEY" > /dev/null 2>&1; then
        echo "[qa] master 패스워드 동기화 완료"
    else
        echo "[qa] ERROR: QA 패스워드 동기화 실패 — 이후 login이 실패할 수 있습니다" >&2
        exit 1
    fi
fi

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

# 유효한 토큰은 언제나 서버 기동 후 login + rotate-token 경로로 발급한다.
# - 신규 DB: init 토큰은 직전 reset-password 호출로 무효화됨 → 재발급 필수
# - 재기동: init이 master를 skip했으므로 init 토큰 자체가 없음 → 재발급 필수
# 조건 분기가 필요 없으므로 항상 실행한다.
echo "[qa] QA Admin 토큰 발급 (login + rotate-token)..."
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

LOGIN_HTTP=$(curl -s -o /tmp/qa_login_resp -w "%{http_code}" \
    -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -c "$COOKIE_JAR" \
    -d "{\"member_id\":\"qa-admin\",\"password\":\"$QA_PASSWORD\"}" || echo "000")
if [ "$LOGIN_HTTP" != "200" ]; then
    echo "[qa] ERROR: login 실패 (HTTP=$LOGIN_HTTP)" >&2
    echo "[qa] login response: $(cat /tmp/qa_login_resp 2>/dev/null || echo '(empty)')" >&2
    exit 1
fi

ROTATE_HTTP=$(curl -s -o /tmp/qa_rotate_resp -w "%{http_code}" \
    -X POST http://localhost:8000/api/members/qa-admin/rotate-token \
    -b "$COOKIE_JAR" || echo "000")
if [ "$ROTATE_HTTP" != "200" ]; then
    echo "[qa] ERROR: rotate-token 실패 (HTTP=$ROTATE_HTTP)" >&2
    echo "[qa] rotate response: $(cat /tmp/qa_rotate_resp 2>/dev/null || echo '(empty)')" >&2
    exit 1
fi
QA_TOKEN=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" < /tmp/qa_rotate_resp 2>/dev/null || true)

case "$QA_TOKEN" in
    "")
        echo "[qa] ERROR: rotate-token 응답에서 토큰을 추출할 수 없습니다" >&2
        exit 1
        ;;
esac

export ANTE_MEMBER_TOKEN="$QA_TOKEN"
echo "export ANTE_MEMBER_TOKEN=\"$QA_TOKEN\"" >> /root/.bashrc
# docker exec는 컨테이너의 환경변수를 상속하지 않으므로
# 토큰을 파일로도 저장하여 CLI가 자동으로 읽을 수 있게 한다
echo -n "$QA_TOKEN" > /run/ante-token
chmod 644 /run/ante-token
# docker exec에서 CLI가 토큰 파일을 찾을 수 있도록 환경변수 파일에도 기록
echo "ANTE_TOKEN_FILE=/run/ante-token" >> /etc/environment
# docker exec 세션이 컨테이너의 export 된 환경변수를 상속하지 않으므로
# ANTE_CONFIG_DIR 도 /etc/environment 에 기록해 tests/tc/ 의 plain `ante ...`
# CLI 호출이 서버와 같은 /app/db/ante.db 를 바라보게 한다
# (Codex 10차 review Finding 1).
echo "ANTE_CONFIG_DIR=/app" >> /etc/environment
echo "[qa] ANTE_MEMBER_TOKEN 설정 완료 (환경변수 + /run/ante-token)"

echo "[qa] QA 시드 계좌 확인 (Treasury 초기화 보장)..."
# 계좌가 없으면 API로 테스트 계좌 생성 → 서버 재기동하여 Treasury 초기화
ACCOUNT_COUNT=$(curl -sf http://localhost:8000/api/accounts | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('accounts',[])))" 2>/dev/null || echo "0")
if [ "$ACCOUNT_COUNT" = "0" ]; then
    echo "[qa] 계좌 없음 — 시드 계좌 생성 중..."
    curl -sf -X POST http://localhost:8000/api/accounts \
        -H "Content-Type: application/json" \
        -d '{"account_id":"test","name":"QA Test","broker_type":"test","trading_mode":"virtual","credentials":{"app_key":"test","app_secret":"test"}}' \
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

echo "[qa] QA 데이터셋 시딩 (봇, 거래, 성과, Parquet)..."
python scripts/qa_seed_datasets.py --db-path db/ante.db --data-path data/

echo "[qa] QA 테스트용 동적 설정 시드 등록..."
sqlite3 db/ante.db "INSERT OR IGNORE INTO dynamic_config (key, value, category, updated_at) VALUES ('risk.test_qa_key', '0', 'risk', datetime('now'));"

echo "[qa] 엔트리포인트 초기화 완료"

# 서버 포그라운드 전환
wait $SERVER_PID
