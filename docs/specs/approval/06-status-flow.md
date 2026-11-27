# Approval 모듈 세부 설계 - 결재 상태 흐름

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# 결재 상태 흐름

```
pending ──→ approved ──→ (자동 실행 성공)
   │            │
   │            └──→ execution_failed (실행 실패)
   │                    │
   │                    ├──→ approved (재승인 → 재실행)
   │                    ├──→ rejected (거절)
   │                    ├──→ on_hold (보류)
   │                    └──→ cancelled (철회)
   │
   ├──→ rejected ──→ pending (재상신: params/body 수정 후 reopen)
   │
   ├──→ cancelled (요청자 철회)
   │
   ├──→ on_hold ──→ pending (보류 해제)
   │                  │
   │                  └──→ cancelled (보류 중 철회)
   │
   └──→ expired (만료 시각 도달)
```

상태 전이는 결재가 처리하는 쪽이 읽은 그 상태에 아직 머물러 있을 때만 일어난다. 같은 결재를 승인·거절·철회·만료 등이 겹쳐 처리하면 한 호출만 전이하고(승인이면 그 호출만 실행한다), 진 쪽은 앞의 처리가 끝난 뒤에 호출했을 때와 같은 오류로 거부된다. 진 쪽이 다시 읽은 상태가 여전히 그 동작을 허용하는 상태이면 상태 충돌 오류(`APPROVAL_STATUS_CONFLICT`)로 거부된다. 만료 처리에서 진 결재는 건너뛴다. 알려진 한계: 읽은 뒤 다른 전이(예: 거절 후 재상신)를 거쳐 같은 상태로 돌아온 경우는 막지 않는다 — 그 호출은 전이하고, 승인이면 먼저 읽어 둔 내용으로 실행한다.
