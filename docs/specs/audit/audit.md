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

### Web API

```
GET /api/audit?member_id=agent-01&action=bot.&from_date=2026-03-12&to_date=2026-03-19&limit=100&offset=0
```

응답: `{ "logs": [...], "total": 42 }`

### CLI

```
ante audit list \
  [--member-id agent-01] \
  [--action "bot."] \
  [--from-date 2026-03-12] \
  [--to-date 2026-03-19] \
  [--limit 100] [--offset 0] \
  [--format json|table]
```

## 감사 로그 기록 지점

AuditLogger는 인프라(기록·조회)만 제공한다. 실제 기록은 **Web API와 CLI** — 사용자/Agent 액션의 진입점에서 수행한다.

### 기록 원칙

- **상태 변경 액션만 기록**: GET/조회는 기록하지 않는다
- **진입점에서 기록**: 서비스 내부가 아닌, Web API 라우트 핸들러와 CLI 커맨드 핸들러에서 호출한다
- **member_id 식별**: Web API는 세션 쿠키(`ante_session`)에서, CLI는 토큰(`ANTE_MEMBER_TOKEN`)에서 추출한다

### Web API 기록 대상

| 엔드포인트 | action | resource 예시 |
|-----------|--------|--------------|
| `POST /auth/login` | `auth.login` | `member:{member_id}` |
| `POST /auth/logout` | `auth.logout` | `member:{member_id}` |
| `PATCH /approvals/{id}/status` | `approval.approve` / `approval.reject` | `approval:{id}` |
| `POST /bots` | `bot.create` | `bot:{bot_id}` |
| `POST /bots/{id}/start` | `bot.start` | `bot:{bot_id}` |
| `POST /bots/{id}/stop` | `bot.stop` | `bot:{bot_id}` |
| `DELETE /bots/{id}` | `bot.delete` | `bot:{bot_id}` |
| `POST /members` | `member.create` | `member:{member_id}` |
| `POST /members/{id}/suspend` | `member.suspend` | `member:{member_id}` |
| `POST /members/{id}/reactivate` | `member.reactivate` | `member:{member_id}` |
| `POST /members/{id}/revoke` | `member.revoke` | `member:{member_id}` |
| `POST /members/{id}/rotate-token` | `member.rotate_token` | `member:{member_id}` |
| `PATCH /members/{id}/password` | `member.change_password` | `member:{member_id}` |
| `PUT /members/{id}/scopes` | `member.update_scopes` | `member:{member_id}` |
| `PUT /config/{key}` | `config.update` | `config:{key}` |
| `POST /treasury/.../allocate` | `treasury.allocate` | `bot:{bot_id}` |
| `POST /treasury/.../deallocate` | `treasury.deallocate` | `bot:{bot_id}` |
| `POST /treasury/balance` | `treasury.set_balance` | `treasury` |
| `POST /system/kill-switch` | `system.halt` / `system.activate` | `system:kill_switch` |
| `POST /reports` | `report.submit` | `report:{report_id}` |
| `DELETE /data/datasets/{id}` | `data.delete_dataset` | `dataset:{dataset_id}` |

### CLI 기록 대상

| 커맨드 | action | resource 예시 |
|--------|--------|--------------|
| `ante approval approve <id>` | `approval.approve` | `approval:{id}` |
| `ante approval reject <id>` | `approval.reject` | `approval:{id}` |
| `ante approval cancel <id>` | `approval.cancel` | `approval:{id}` |
| `ante system halt` | `system.halt` | `system:kill_switch` |
| `ante system activate` | `system.activate` | `system:kill_switch` |
| `ante bot create` | `bot.create` | `bot:{bot_id}` |
| `ante bot remove <id>` | `bot.delete` | `bot:{bot_id}` |

### 구현 방식 — 이중 구조

감사 로그는 **미들웨어 안전망 + 핸들러 명시적 호출**의 이중 구조로 기록한다.
새 엔드포인트가 추가될 때 핸들러에서 audit 호출을 빠뜨려도, 미들웨어가 최소한의 기록을 보장한다.

| 계층 | 역할 | 기록 내용 |
|------|------|----------|
| **미들웨어** (안전망) | 모든 상태 변경 API를 자동 포착 | `action=api:post`, `resource=/api/bots/bot-001/stop` — 최소한의 정보 |
| **핸들러** (명시적) | 의미 있는 세부 정보 보강 | `action=bot.stop`, `resource=bot:bot-001`, `detail=...` |

#### Web API — AuditMiddleware (안전망)

모든 POST/PUT/DELETE/PATCH 요청 중 성공(2xx)한 것을 자동 기록한다.
핸들러에서 이미 명시적으로 기록한 경우에도 미들웨어 레코드가 별도로 남는다 — 이중 기록은 감사 목적상 문제가 되지 않으며, `action` 접두사(`api:` vs `bot.` 등)로 구분 가능하다.

```python
class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if 200 <= response.status_code < 400:
                member_id = getattr(request.state, "member_id", "anonymous")
                await self.audit_logger.log(
                    member_id=member_id,
                    action=f"api:{request.method.lower()}",
                    resource=request.url.path,
                    ip=request.client.host if request.client else "",
                )
        return response
```

`app.py`에서 CORSMiddleware와 함께 등록한다.

#### Web API — 핸들러 명시적 호출 (보강)

각 라우트 핸들러에서 상태 변경 성공 후 `audit_logger.log()`를 호출한다. 미들웨어보다 정확한 action/resource/detail을 기록한다.

```python
# 라우트 핸들러 예시 (bots.py)
@router.post("/bots/{bot_id}/stop")
async def stop_bot(bot_id: str, request: Request):
    await bot_manager.stop_bot(bot_id)
    await audit_logger.log(
        member_id=request.state.member_id,
        action="bot.stop",
        resource=f"bot:{bot_id}",
        ip=request.client.host,
    )
    return {"status": "ok"}
```

#### CLI — 명시적 호출

CLI는 진입점이 명확하고 커맨드 수가 한정적이므로, 미들웨어 없이 명시적 호출만으로 충분하다.

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

중요 이벤트(킬 스위치, 결재 등)는 별도 테이블(approval history, notification_history)에도 기록되므로, 감사 로그 삭제 후에도 추적 경로가 유지된다.

## 미결 사항

없음.
