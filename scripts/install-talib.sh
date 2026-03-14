#!/usr/bin/env bash
# TA-Lib C 라이브러리 + Python 바인딩 설치 스크립트.
# 사용법: bash scripts/install-talib.sh
set -euo pipefail

TALIB_VERSION="0.4.0"
TALIB_URL="https://sourceforge.net/projects/ta-lib/files/ta-lib/${TALIB_VERSION}/ta-lib-${TALIB_VERSION}-src.tar.gz"

echo "=== TA-Lib C 라이브러리 설치 ==="

OS="$(uname -s)"
case "${OS}" in
    Darwin)
        echo "[macOS] Homebrew로 설치합니다."
        if command -v brew &>/dev/null; then
            brew install ta-lib
        else
            echo "ERROR: Homebrew가 설치되어 있지 않습니다."
            echo "  https://brew.sh 에서 설치 후 다시 실행하세요."
            exit 1
        fi
        ;;
    Linux)
        echo "[Linux] 소스에서 빌드합니다."
        # 빌드 도구 확인
        if ! command -v gcc &>/dev/null; then
            echo "gcc를 설치합니다..."
            if command -v apt-get &>/dev/null; then
                sudo apt-get update && sudo apt-get install -y build-essential wget
            elif command -v yum &>/dev/null; then
                sudo yum groupinstall -y "Development Tools" && sudo yum install -y wget
            else
                echo "ERROR: 패키지 매니저를 찾을 수 없습니다. gcc를 수동 설치하세요."
                exit 1
            fi
        fi

        TMPDIR="$(mktemp -d)"
        echo "소스 다운로드: ${TALIB_URL}"
        wget -q -O "${TMPDIR}/ta-lib.tar.gz" "${TALIB_URL}"
        tar -xzf "${TMPDIR}/ta-lib.tar.gz" -C "${TMPDIR}"
        cd "${TMPDIR}/ta-lib"
        ./configure --prefix=/usr/local
        make -j"$(nproc)"
        sudo make install
        sudo ldconfig
        rm -rf "${TMPDIR}"
        echo "C 라이브러리 설치 완료 (/usr/local/lib)"
        ;;
    *)
        echo "ERROR: 지원하지 않는 OS: ${OS}"
        exit 1
        ;;
esac

echo ""
echo "=== Python 바인딩 설치 ==="
pip install TA-Lib
echo ""
echo "=== 설치 검증 ==="
python -c "import talib; print(f'TA-Lib {talib.__version__} 설치 완료')"
echo "완료!"
