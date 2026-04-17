# Config 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 참고 구현체 분석

| 구현체 | 설정 파일 | 비밀값 | 동적 설정 | 유효성 검증 |
|--------|----------|--------|----------|------------|
| NautilusTrader | YAML + Python config 객체 | 환경변수 | X (재시작 필요) | Pydantic 모델 |
| FreqTrade | JSON (user_data/config.json) | JSON 내 포함 | 부분적 (RPC) | jsonschema |
| Prefect | TOML (profiles.toml) | 환경변수 (`PREFECT_*`) | O (서버 사이드) | Pydantic Settings |
| Django | Python 파일 (settings.py) | 환경변수 + django-environ | O (constance 등 별도) | 타입 체크 |
