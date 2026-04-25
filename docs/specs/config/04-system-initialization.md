# Config 모듈 세부 설계 - 시스템 초기화 순서에서의 위치

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 시스템 초기화 순서에서의 위치

```
1. Config.load() + Config.validate()
2. Instance path resolver 확정 (`config_dir` 기준 DB/data/PID/socket/logs 경로 정규화)
3. Logging 초기화 (`logging.directory` 참조)
4. Database 초기화 (`db.path` 참조)
5. EventBus 초기화
6. SystemState 초기화 (DB + EventBus 주입)
7. DynamicConfigService 초기화 (DB + EventBus 주입)
8. 나머지 모듈 초기화 — 전체 순서는 architecture.md 참조
```

모든 상대 경로는 CWD가 아니라 `config_dir` 기준으로 해석한다. 서버와 CLI가 같은
`--config-dir` 또는 `ANTE_CONFIG_DIR`을 사용하면 같은 DB, data root, IPC socket을 공유한다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
