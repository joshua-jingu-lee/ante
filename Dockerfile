# Stage 1: 프론트엔드 빌드
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY pyproject.toml ../pyproject.toml
RUN npm run build

# Stage 2: Python 런타임
FROM python:3.12-slim AS runtime
WORKDIR /app

# 시스템 의존성
# tzdata: Python `zoneinfo.ZoneInfo("Asia/Seoul")` 조회를 위한 IANA DB.
# 로그 회전은 핸들러 코드에서 KST 를 강제하므로 `ENV TZ` 자체는 필수 아님이나,
# `date`, 컨테이너 로그 타임스탬프 등 관측성 일관성을 위해 함께 설정한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 관측성 TZ (회전 자정 경계는 코드가 KST 로 고정하므로 이 ENV 는 필수 아님).
ENV TZ=Asia/Seoul

# Python 패키지 설치
COPY pyproject.toml ./
COPY src/ src/

# 프론트엔드 빌드 산출물을 패키지 경로에 복사
COPY --from=frontend-build /build/dist src/ante/web/static

RUN pip install --no-cache-dir .

# 런타임 디렉토리
RUN mkdir -p config data db

# 기본 설정 파일 복사 (Docker에서는 웹 대시보드 기본 활성화)
COPY config/system.toml.example config/system.toml
RUN sed -i 's/^enabled = false/enabled = true/' config/system.toml

EXPOSE 3982

ENTRYPOINT ["python", "-m", "ante.main"]
