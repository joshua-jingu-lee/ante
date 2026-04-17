# Approval 모듈 세부 설계 - ApprovalRequest 모델

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# ApprovalRequest 모델

```python
@dataclass
class ApprovalRequest:
    id: str                     # UUID
    type: str                   # 요청 유형 (아래 표 참조)
    status: str                 # pending | approved | rejected | on_hold | expired | cancelled
    requester: str              # 요청자 식별 (예: "agent", "agent:strategy-dev")
    title: str                  # 요청 제목 (사람이 읽을 수 있는 요약)
    body: str                   # 본문 (사유, 현황 분석, 기대 효과 등 자유 형식)
    params: dict                # 유형별 실행 파라미터
    reviews: list[dict] = []    # 사전 검증 결과 (아래 참조)
    history: list[dict] = []    # 감사 이력 (아래 참조)
    reference_id: str = ""      # 참조 ID (report_id 등)
    expires_at: str = ""        # 만료 시각 (빈 문자열이면 만료 없음)
    created_at: str = ""        # 생성 시각
    resolved_at: str = ""       # 처리 시각
    resolved_by: str = ""       # 처리자 ("user" 등)
    reject_reason: str = ""     # 거절 사유
```

### reviews (사전 검증)

결재 요청이 생성되면, 관련 모듈이나 참조자가 사전 검증을 수행하여 결과를 `reviews`에 첨부한다.
사용자는 검증 결과를 참고하여 승인 여부를 판단한다.

```python
# review 구조
{
    "reviewer": str,    # 검증 주체 (예: "treasury", "rule_engine", "agent:risk-analyst")
    "result": str,      # "pass" | "warn" | "fail"
    "detail": str,      # 검증 상세 (예: "가용 잔액 3,000만원, 요청 금액 2,500만원 → 충족")
    "reviewed_at": str, # 검증 시각
}
```

**검증 주체의 유형:**

| 유형 | 예시 | 설명 |
|------|------|------|
| 시스템 모듈 | `treasury`, `rule_engine` | 요청 생성 시 자동으로 검증 수행 |
| 외부 Agent | `agent:risk-analyst`, `agent:cfo` | 자금팀장 역할 등 특정 역할을 맡은 Agent가 CLI로 검토 의견 첨부 |

현재는 시스템 모듈만 자동 검증하지만, 향후 역할별 Agent(리스크 분석, 자금 관리 등)가 참조자로 참여하여 검토 의견을 남길 수 있다. 검증 주체가 사람이든 시스템이든 Agent든, `reviews`에 동일한 형식으로 기록된다.

```
Agent(전략 개발): 결재 요청 생성 (budget_change)
  → Treasury: 자동 검증 → review 첨부 ("pass", "잔액 충분")
  → Agent(자금팀장): CLI로 검토 → review 첨부 ("pass", "리스크 허용 범위 내")
  → 사용자: 검증 결과를 보고 승인
```
