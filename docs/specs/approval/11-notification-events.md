# Approval 모듈 세부 설계 - 알림 이벤트 정의 (Notification Events)

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 알림 이벤트 정의 (Notification Events)

### 1. 결재 요청 알림

> 소스: `src/ante/approval/service.py` — ApprovalService.create()

**트리거**: 새 결재 요청이 생성될 때 (전결 시에도 발행, `[자동 승인]` 접두사 표시)

**데이터 수집**:
- `request.type` → 결재 유형
- `request.title` → 요청 제목
- `request.requester` → 요청자
- `request.id` → 문서 ID
- `auto_approved` → 전결 여부 (전결이 아니면 인라인 버튼 포함)

**발행 메시지**:

```
level: info
title: 결재 요청
category: approval
buttons: [[승인, 거절]]  (전결 시 없음)

{prefix}유형: `{type}`
제목: {title}
요청자: `{requester}`
ID: `{id}`
```

### 2. 결재 처리 완료

> 소스: `src/ante/approval/service.py` — ApprovalService.approve() / reject()

**트리거**: 결재가 승인·거절·철회·만료 등으로 최종 처리될 때

**데이터 수집**:
- `approval_type` → 결재 유형
- `resolution` → 처리 결과 (approved, rejected, cancelled, expired 등)
- `resolved_by` → 처리자
- `approval_id` → 문서 ID
- `title` → 요청 제목
- `reject_reason` → 거절 사유 (거절 시)
- 예외 발생 여부 → executor 실행 실패, 이미 처리됨, 만료됨, ID 없음

**중복 알림 방지 정책**: 텔레그램 명령(`/approve`, `/reject`, 인라인 버튼)으로 처리된 경우 직접 응답(reply)만 발송하고 NotificationEvent는 발행하지 않는다. 대시보드·CLI 등 텔레그램 외 채널에서 처리된 경우에만 NotificationEvent를 발행한다. 이를 통해 사용자는 어떤 채널에서 처리하든 정확히 1번만 메시지를 수신한다.

**NotificationEvent 발행** (대시보드·CLI 등 텔레그램 외 채널에서 처리 시):

```
level: info
title: 결재 처리 완료
category: approval

유형: `{type}`
결과: *{resolution}*
처리자: `{resolved_by}`
ID: `{id}`
```

**텔레그램 명령 직접 응답** (텔레그램에서 처리 시, 명령 발신자에게 reply):

| 결과 | `/approve` 응답 | `/reject` 응답 |
|------|-----------------|----------------|
| 성공 | `✅ 결재 승인 완료\n제목: {title}\nID: {id}` | `❌ 결재 거절 완료\n제목: {title}\nID: {id}\n사유: {reason}` |
| executor 실행 실패 | `⚠️ 승인되었으나 실행 실패\n제목: {title}\nID: {id}\n사유: {error}` | — |
| 이미 처리됨 | `ℹ️ 이미 처리된 결재입니다 ({status})\nID: {id}` | 동일 |
| 만료됨 | `ℹ️ 만료된 결재입니다\nID: {id}` | 동일 |
| ID 없음 | `❌ 결재를 찾을 수 없습니다\nID: {id}` | 동일 |

> 인라인 버튼으로 거절 시 사유는 기본값(`"사용자 거절"`)을 사용한다. 상세 사유가 필요하면 `/reject <id> <reason>` 명령어를 직접 입력한다.
