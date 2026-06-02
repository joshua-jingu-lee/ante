# Audit 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/audit/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 감사 로그, [member.md](../member/member.md) 멤버 인증

## 개요

Audit 모듈은 **멤버(사용자/에이전트) 액션의 감사 로그를 기록하고 조회하는 모듈**이다.
누가, 언제, 무엇을 했는지 추적하여 시스템 운영의 투명성과 보안을 보장한다.

**주요 기능**:
- **감사 로그 기록**: 멤버 ID, 액션, 리소스, 상세 정보, IP 주소를 기록
- **감사 로그 조회**: 멤버별, 액션별 필터링 + 페이지네이션 지원
- **건수 조회**: 조건별 로그 건수 반환

## AuditLogger 인터페이스

### 생성자

```python
AuditLogger(db: Database)
```

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | `audit_log` 테이블 스키마 생성 |
| `log` | *, member_id: str, action: str, resource: str = "", detail: str = "", ip: str = "" | None | 감사 로그 기록 |
| `query` | *, member_id: str \| None, action: str \| None, from_date: str \| None, to_date: str \| None, limit: int = 50, offset: int = 0 | list[dict] | 감사 로그 조회 (최신순, 페이지네이션). limit 최대값 200 |
| `count` | *, member_id: str \| None, action: str \| None, from_date: str \| None, to_date: str \| None | int | 조건에 맞는 감사 로그 건수 조회 |
| `cleanup` | retention_days: int | int | 보존 기간 초과 로그 삭제. 삭제 건수 반환 |

### 조회 제약 및 필터

**페이지네이션 제약**:

| 파라미터 | 기본값 | 최대값 | 설명 |
|----------|--------|--------|------|
| `limit` | 50 | 200 | 한 번에 반환하는 최대 건수. 200 초과 요청 시 200으로 클램핑 |
| `offset` | 0 | — | 페이지네이션 오프셋 |

**필터 파라미터**:

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `member_id` | str \| None | 멤버 ID 완전 일치 |
| `action` | str \| None | 액션 접두사 일치 (예: `"bot."` → `bot.create`, `bot.stop` 등 매칭) |
| `from_date` | str \| None | 시작 날짜 (ISO 8601, 예: `"2026-03-01"` 또는 `"2026-03-01T09:00:00"`) |
| `to_date` | str \| None | 종료 날짜 (ISO 8601, 해당 날짜 포함) |

```python
# 조회 예시: 최근 7일간 봇 관련 감사 로그
await audit_logger.query(
    action="bot.",
    from_date="2026-03-12",
    to_date="2026-03-19",
    limit=100,
)
```

## 데이터베이스 스키마

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL DEFAULT '',
    detail      TEXT DEFAULT '',
    ip          TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_member ON audit_log(member_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
```

## 감사 로그 조회 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-audit--감사-로그-조회)다.

`--format`은 root 전역 옵션(`--format text|json`, `table` 미지원)이므로
`ante` 바로 뒤에 둔다.

```
ante --format json audit list \
  [--member agent-01] \
  [--action "bot."] \
  [--from-date 2026-03-12] \
  [--to-date 2026-03-19] \
  [--limit 100] [--offset 0]
```

## 감사 로그 기록 지점

AuditLogger는 인프라(기록·조회)만 제공한다. 실제 기록은 **CLI/IPC** — 사용자/Agent 액션의 진입점에서 수행한다.

### 기록 원칙

- **상태 변경 액션만 기록**: GET/조회는 기록하지 않는다
- **진입점에서 기록**: 서비스 내부가 아닌, CLI 커맨드 핸들러나 IPC handler에서 호출한다
- **member_id 식별**: CLI는 토큰(`ANTE_MEMBER_TOKEN`)에서 추출하고 IPC에는 검증된 actor를 전달한다

### CLI/IPC 기록 대상

| 커맨드 | action | resource 예시 |
|--------|--------|--------------|
| `ante approval approve <id>` | `approval.approve` | `approval:{id}` |
| `ante approval reject <id>` | `approval.reject` | `approval:{id}` |
| `ante approval cancel <id>` | `approval.cancel` | `approval:{id}` |
| `ante system halt` | `system.halt` | `system:kill_switch` |
| `ante system clear-halt` | `system.clear_halt` | `system:kill_switch` |
| `ante bot create` | `bot.create` | `bot:{bot_id}` |
| `ante bot start <id>` | `bot.start` | `bot:{bot_id}` |
| `ante bot stop <id>` | `bot.stop` | `bot:{bot_id}` |
| `ante bot remove <id>` | `bot.delete` | `bot:{bot_id}` |
| `ante bot signal-key <id> --rotate` | `bot.signal_key.rotate` | `bot:{bot_id}` |
| `ante broker reconcile --fix` | `broker.reconcile` | `account:{account_id}` |
| `ante member register` | `member.register` | `member:{member_id}` |
| `ante member set-emoji <id> <emoji>` | `member.set_emoji` | `member:{member_id}` |
| `ante member update-scopes <id>` | `member.update_scopes` | `member:{member_id}` |
| `ante member suspend <id>` | `member.suspend` | `member:{member_id}` |
| `ante member reactivate <id>` | `member.reactivate` | `member:{member_id}` |
| `ante member revoke <id>` | `member.revoke` | `member:{member_id}` |
| `ante member rotate-token <id>` | `member.rotate_token` | `member:{member_id}` |
| `ante member reset-password` | `member.reset_password` | `member:{master_member_id}` |
| `ante member regenerate-recovery-key` | `member.regenerate_recovery_key` | `member:{master_member_id}` |

`ante bot start`/`ante bot stop`은 audit action(`bot.start`/`bot.stop`) 이름을
사용한다. 봇 생애주기 변경은 단일 audit action namespace로 모인다.
`ante bot status`는 read-only live 조회이므로 audit 대상이 아니다
(상태 변경 액션만 기록하는 audit 기록 원칙).

`ante member reset-password`/`ante member regenerate-recovery-key`는 인증 불필요
(auth-exempt) 커맨드다. 대상은 항상 master 멤버이며 그 `member_id`는 서버 handler가
master-lookup으로 해석해 `resource`에 기록한다. 다만 audit row의 `member_id`(행위자)는
client가 보낸 actor(스푸핑 가능)를 신뢰하지 않고 handler가 고정한 sentinel 상수
(`recovery`)로 기록한다. recovery key, 새/현재 password 등 비밀값은 audit detail,
audit_log, IPC error envelope, server 로그 어디에도 기록하지 않는다.

### 구현 방식

CLI/IPC는 진입점이 명확하고 커맨드 수가 한정적이므로, 명시적 호출로 기록한다.

```python
# CLI 커맨드 예시 (approval.py)
async def _approve(ctx, approval_id):
    await approval_service.approve(approval_id, resolved_by=ctx.member_id)
    await audit_logger.log(
        member_id=ctx.member_id,
        action="approval.approve",
        resource=f"approval:{approval_id}",
    )
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## 보존 기간 정책 (Retention)

90일 이전의 감사 로그를 자동 삭제한다. `system.toml`에서 보존 기간을 설정할 수 있으며, 0이면 삭제하지 않는다(무기한 보존).

```toml
[audit]
retention_days = 90    # 기본 90일. 0이면 무기한 보존
```

`AuditLogger.cleanup(retention_days)` 메서드를 추가하고, `main.py`에서 하루 1회 주기적 태스크로 실행한다.

```python
# main.py
async def _audit_cleanup_loop(audit_logger: AuditLogger, retention_days: int = 90):
    while True:
        await asyncio.sleep(86400)  # 24시간
        if retention_days > 0:
            deleted = await audit_logger.cleanup(retention_days)
            if deleted:
                logger.info("감사 로그 정리: %d건 삭제 (보존 %d일)", deleted, retention_days)
```

중요 이벤트(킬 스위치, 결재 등)는 감사 로그와 별개로 각 도메인의 소유 저장소에도 남을 수 있다. 결재 상태 전이는 Approval history가 추적하고, 알림 발송 이력은 별도 `notification_history` 테이블을 두지 않고 텔레그램 채팅방 자체를 운영 이력으로 본다.
