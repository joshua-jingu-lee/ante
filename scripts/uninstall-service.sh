#!/usr/bin/env bash
# Ante 시스템 서비스 제거 스크립트.
# 사용법: sudo bash scripts/uninstall-service.sh
set -euo pipefail

echo "=== Ante 서비스 제거 ==="

OS="$(uname -s)"
case "${OS}" in
    Linux)
        echo "[Linux] systemd 서비스를 제거합니다."

        if systemctl is-active --quiet ante.service 2>/dev/null; then
            systemctl stop ante.service
            echo "서비스 중지 완료"
        fi

        if systemctl is-enabled --quiet ante.service 2>/dev/null; then
            systemctl disable ante.service
            echo "자동 시작 비활성화"
        fi

        if [ -f /etc/systemd/system/ante.service ]; then
            rm /etc/systemd/system/ante.service
            systemctl daemon-reload
            echo "서비스 파일 제거 완료"
        fi

        echo ""
        echo "=== 제거 완료 ==="
        echo "데이터 디렉토리(/opt/ante)는 보존됩니다."
        echo "완전 삭제: rm -rf /opt/ante && userdel ante"
        ;;

    Darwin)
        echo "[macOS] launchd 서비스를 제거합니다."

        PLIST="${HOME}/Library/LaunchAgents/com.ante.plist"
        if [ -f "${PLIST}" ]; then
            launchctl unload "${PLIST}" 2>/dev/null || true
            rm "${PLIST}"
            echo "서비스 제거 완료"
        else
            echo "서비스 파일이 없습니다: ${PLIST}"
        fi

        echo ""
        echo "=== 제거 완료 ==="
        echo "데이터 디렉토리(/opt/ante)는 보존됩니다."
        ;;

    *)
        echo "ERROR: 지원하지 않는 OS: ${OS}"
        exit 1
        ;;
esac
