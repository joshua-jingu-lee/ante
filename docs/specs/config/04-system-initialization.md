# Config 모듈 세부 설계 - 시스템 초기화 순서에서의 위치

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 시스템 초기화 순서에서의 위치

```
1. Config.load() + Config.validate()
2. Database 초기화 (Config에서 db.path 참조)
3. EventBus 초기화
4. SystemState 초기화 (DB + EventBus 주입)
5. DynamicConfigService 초기화 (DB + EventBus 주입)
6. 나머지 모듈 초기화 — 전체 순서는 architecture.md 참조
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
