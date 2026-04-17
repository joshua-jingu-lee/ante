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
