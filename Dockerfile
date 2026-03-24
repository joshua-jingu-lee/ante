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
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

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
