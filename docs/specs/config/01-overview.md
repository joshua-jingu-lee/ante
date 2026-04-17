# Config 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 개요

Config 모듈은 Ante의 **모든 설정에 대한 통일된 접근 인터페이스**를 제공한다.
설정의 성격에 따라 3계층(정적 TOML / 비밀값 .env / 동적 SQLite)으로 분리하며,
모듈들은 Config를 통해 일관된 방식으로 설정에 접근한다.

**주요 기능**:
- **3계층 설정 분리**: 정적 설정(TOML), 비밀값(.env + 환경변수), 동적 설정(SQLite) — 각 성격에 맞는 저장소와 변경 주기
- **통일된 접근 API**: `Config.get()` (정적), `Config.secret()` (비밀값), `DynamicConfigService` (동적) — 모듈별 설정 접근 패턴 일관화
- **동적 설정 즉시 반영**: SQLite CRUD + EventBus(`ConfigChangedEvent`) 알림으로 재시작 없이 런타임 변경 적용
- **시작 시 유효성 검증**: 필수 설정 존재 여부 및 타입을 시작 시점에 전체 검증 (Fail-fast)
