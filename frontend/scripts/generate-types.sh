#!/usr/bin/env bash
# OpenAPI → TypeScript 타입 자동 생성 스크립트
#
# 사용법:
#   npm run generate-types                          # 로컬 JSON 파일 기반 (기본)
#   npm run generate-types -- --url http://...      # 서버에서 OpenAPI 스키마 가져오기
#
# 로컬 파일 기반:
#   1. 백엔드 서버에서 /openapi.json 다운로드 → frontend/openapi.json 저장
#   2. 이 스크립트 실행
#
# 서버 기반:
#   1. 백엔드 서버 실행 (기본: http://localhost:8000)
#   2. npm run generate-types -- --url http://localhost:8000/openapi.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$FRONTEND_DIR/src/types/api.generated.ts"
LOCAL_SCHEMA="$FRONTEND_DIR/openapi.json"

# 기본값
SOURCE=""
URL=""

# 인자 파싱
while [[ $# -gt 0 ]]; do
  case $1 in
    --url)
      URL="$2"
      shift 2
      ;;
    --url=*)
      URL="${1#*=}"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# 소스 결정
if [[ -n "$URL" ]]; then
  echo "서버에서 OpenAPI 스키마를 가져옵니다: $URL"
  SOURCE="$URL"
elif [[ -f "$LOCAL_SCHEMA" ]]; then
  echo "로컬 OpenAPI 스키마를 사용합니다: $LOCAL_SCHEMA"
  SOURCE="$LOCAL_SCHEMA"
else
  echo "오류: OpenAPI 스키마를 찾을 수 없습니다."
  echo ""
  echo "다음 중 하나를 수행하세요:"
  echo "  1. frontend/openapi.json 파일 배치 후 재실행"
  echo "     curl http://localhost:8000/openapi.json -o frontend/openapi.json"
  echo "  2. 서버 URL 직접 지정"
  echo "     npm run generate-types -- --url http://localhost:8000/openapi.json"
  exit 1
fi

echo "타입 생성 중..."
npx openapi-typescript "$SOURCE" \
  --output "$OUTPUT_FILE" \
  --export-type \
  --root-types \
  --root-types-no-schema-prefix \
  --alphabetize

echo "생성 완료: $OUTPUT_FILE"
