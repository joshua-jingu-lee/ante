#!/usr/bin/env bash
# Ante 시스템 서비스 설치 스크립트.
# Linux (systemd) 또는 macOS (launchd)를 자동 감지하여 설치한다.
# 사용법: sudo bash scripts/install-service.sh
set -euo pipefail

ANTE_HOME="${ANTE_HOME:-/opt/ante}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Ante 서비스 설치 ==="
echo "ANTE_HOME: ${ANTE_HOME}"

OS="$(uname -s)"
case "${OS}" in
    Linux)
        echo "[Linux] systemd 서비스를 설치합니다."

        # ante 사용자 생성 (없으면)
        if ! id -u ante &>/dev/null; then
            echo "ante 사용자 생성..."
            useradd --system --home-dir "${ANTE_HOME}" --shell /usr/sbin/nologin ante
        fi

        # 디렉토리 준비
        mkdir -p "${ANTE_HOME}"/{db,data,logs}
        chown -R ante:ante "${ANTE_HOME}"

        # 서비스 파일 복사
        cp "${SCRIPT_DIR}/deploy/ante.service" /etc/systemd/system/ante.service

        # 경로 치환 (ANTE_HOME이 기본값과 다를 때)
        if [ "${ANTE_HOME}" != "/opt/ante" ]; then
            sed -i "s|/opt/ante|${ANTE_HOME}|g" /etc/systemd/system/ante.service
        fi

        # systemd 등록
        systemctl daemon-reload
        systemctl enable ante.service
        systemctl start ante.service

        echo ""
        echo "=== 설치 완료 ==="
        echo "상태 확인: systemctl status ante"
        echo "로그 확인: journalctl -u ante -f"
        ;;

    Darwin)
        echo "[macOS] launchd 서비스를 설치합니다."

        # 디렉토리 준비
        mkdir -p "${ANTE_HOME}"/{db,data,logs}

        # plist 복사
        PLIST_DST="${HOME}/Library/LaunchAgents/com.ante.plist"
        cp "${SCRIPT_DIR}/deploy/com.ante.plist" "${PLIST_DST}"

        # 경로 치환
        if [ "${ANTE_HOME}" != "/opt/ante" ]; then
            sed -i '' "s|/opt/ante|${ANTE_HOME}|g" "${PLIST_DST}"
        fi

        # launchd 등록
        launchctl load "${PLIST_DST}"

        echo ""
        echo "=== 설치 완료 ==="
        echo "상태 확인: launchctl list | grep ante"
        echo "로그 확인: tail -f ${ANTE_HOME}/logs/ante.out.log"
        ;;

    *)
        echo "ERROR: 지원하지 않는 OS: ${OS}"
        exit 1
        ;;
esac
