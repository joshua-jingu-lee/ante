# Web API 모듈 세부 설계 - SessionService

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# SessionService — 서버사이드 세션 관리

> 소스: [`src/ante/web/session.py`](../../../src/ante/web/session.py)

SQLite 기반 서버사이드 세션 저장소. `sessions` 테이블에 세션 ID, 멤버 ID, 만료 시각 등을 관리한다.

## 생성자 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `db` | Database | (필수) | SQLite 연결 인스턴스 |
| `ttl_hours` | int | 24 | 세션 TTL (시간) |

## 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | sessions 테이블 스키마 생성 |
| `create` | member_id: str, ip_address: str = "", user_agent: str = "" | str | 세션 생성. session_id 반환 |
| `validate` | session_id: str | dict \| None | 세션 유효성 확인. 유효하면 세션 데이터, 만료/미존재 시 None |
| `delete` | session_id: str | None | 세션 삭제 |
| `delete_by_member` | member_id: str | None | 멤버의 모든 세션 삭제 |
| `cleanup_expired` | — | int | 만료된 세션 일괄 삭제. 삭제 건수 반환 |

## Member 변경 연동

서버 실행 중 member 상태·토큰·패스워드·복구키 변경은 CLI IPC 또는 Web API가 같은
서버 프로세스 안에서 처리한다. 다음 작업은 성공 직후 `delete_by_member(member_id)`로
기존 웹 세션을 무효화한다:

- `member suspend`
- `member revoke`
- `member reset-password`
- `member change-password`

토큰 재발급(`member rotate-token`)은 CLI/API 토큰 해시를 즉시 교체한다. 세션 쿠키까지
무효화할지는 정책 선택 사항이지만, 보안 사고 대응 경로에서는 `delete_by_member`를 함께
호출할 수 있어야 한다.
