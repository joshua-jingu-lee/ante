# Python 런타임
FROM python:3.13-slim
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

RUN pip install --no-cache-dir .

# 런타임 디렉토리
RUN mkdir -p config data db

ENTRYPOINT ["python", "-m", "ante.main"]
