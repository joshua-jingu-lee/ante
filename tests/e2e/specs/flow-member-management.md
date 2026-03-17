# Flow: 멤버 관리

Human 멤버와 Agent 멤버의 조회, 등록, 상태 관리 및 상세 정보 확인 흐름.

## Seed Data

- **Human 멤버** (2명)
  - owner: role=master, status=active, org="default", 아바타=🦁, 왕관 표시, 마지막 활동=2026-03-13 09:30
  - admin-01: name="운영 관리자", role=admin, status=active, org="operations", 아바타=🐻, 마지막 활동=2026-03-12 18:00
- **Agent 멤버** (6명)
  - strategy-dev-01: name="전략 리서치 1호", status=active, org="strategy-lab", 아바타=🦊, scopes=[strategy:write, data:read, backtest:run, report:write], 마지막 활동=2026-03-13 09:30
  - strategy-dev-02: name="전략 리서치 2호", status=active, org="strategy-lab", 아바타=🐼, scopes=[strategy:write, data:read, backtest:run], 마지막 활동=2026-03-13 08:45
  - risk-monitor: name="리스크 감시", status=active, org="risk", 아바타=🦉, scopes=[bot:read, data:read, approval:review], 마지막 활동=2026-03-13 09:15
  - treasury-agent: name="자금 관리", status=active, org="treasury", 아바타=🐳, scopes=[approval:create, data:read], 마지막 활동=2026-03-13 08:15
  - ops-agent-01: name="봇 운영 1호", status=suspended, org="operations", 아바타=🐧, scopes=[bot:read, data:read], 마지막 활동=2026-03-10 16:00
  - old-agent-01: name="구 리서치 에이전트", status=revoked, org="default", 아바타=🐺, 마지막 활동=2026-02-15 12:00
- **소속 목록**: default, strategy-lab, risk, treasury, operations
- **권한 범위 목록**: strategy:read, strategy:write, report:write, approval:create, approval:review, bot:read, data:read, data:write, backtest:run
- **에이전트 상세 (strategy-dev-01)**
  - 생성일: 2026-02-15 10:00, 생성자: owner
  - 토큰 접두어: "ante_ak_****"

---

## 1. 멤버 관리 페이지 진입

1. 사이드바에서 "🧑‍💼 에이전트 관리" 클릭
2. **Expected**: `/members` 페이지로 이동
3. **Expected**: 헤더에 "멤버 관리" 타이틀 표시
4. **Expected**: 2개 섹션 — "👤 Human 멤버", "☯ Agent 멤버"

## 2. Human 멤버 섹션

1. "👤 Human 멤버" 섹션 확인
2. **Expected**: 섹션 타이틀 + 건수 뱃지 "2" 표시
3. **Expected**: 2개의 멤버 카드 표시

## 3. Human 멤버 — owner 카드

1. owner 카드 확인
2. **Expected**: 아바타 🦁 + 왕관 👑 표시
3. **Expected**: ID: "owner", 이름: "대표"
4. **Expected**: 역할 뱃지 "master" (보라색)
5. **Expected**: 상태: "active" 뱃지 (파란색/positive)
6. **Expected**: 소속: "default"
7. **Expected**: 마지막 활동: "2026-03-13 09:30"
8. **Expected**: 액션: "비밀번호 변경" 버튼만 표시 (정지 버튼 없음)

## 4. Human 멤버 — admin 카드

1. admin-01 카드 확인
2. **Expected**: 아바타 🐻 (왕관 없음)
3. **Expected**: ID: "admin-01", 이름: "운영 관리자"
4. **Expected**: 역할 뱃지 "admin" (회색/muted)
5. **Expected**: 상태: "active" 뱃지 (파란색/positive)
6. **Expected**: 소속: "operations"
7. **Expected**: 마지막 활동: "2026-03-12 18:00"
8. **Expected**: 액션: "정지", "비밀번호 변경" 버튼 표시

## 5. Agent 멤버 섹션 — 헤더

1. "☯ Agent 멤버" 섹션 확인
2. **Expected**: 섹션 타이틀 + 건수 뱃지 "6" 표시
3. **Expected**: 우측에 "+ 에이전트 등록" 버튼 표시

## 6. Agent 멤버 — 필터 구조

1. 필터 영역 확인
2. **Expected**: 상태 필터 탭 4개 — 전체, active, suspended, revoked
3. **Expected**: "전체" 탭이 기본 선택 상태
4. **Expected**: 소속 셀렉트 — 6개 옵션 (전체 소속, default, strategy-lab, risk, treasury, operations)

## 7. Agent 멤버 — active 카드 (strategy-dev-01)

1. strategy-dev-01 카드 확인
2. **Expected**: 카드 전체가 링크 (클릭 시 상세 페이지 이동)
3. **Expected**: 아바타 🦊 (파란색 배경)
4. **Expected**: ID: "strategy-dev-01", 이름: "전략 리서치 1호"
5. **Expected**: 상태 뱃지 "active" (파란색/positive)
6. **Expected**: 소속: "strategy-lab" 뱃지 (회색/muted)
7. **Expected**: 마지막 활동: "2026-03-13 09:30"
8. **Expected**: 권한 범위 태그 4개 — strategy:write, data:read, backtest:run, report:write
9. **Expected**: 액션: "정지", "폐기" 버튼 표시

## 8. Agent 멤버 — suspended 카드 (ops-agent-01)

1. ops-agent-01 카드 확인
2. **Expected**: 아바타 🐧
3. **Expected**: ID: "ops-agent-01", 이름: "봇 운영 1호"
4. **Expected**: 상태 뱃지 "suspended" (노란색)
5. **Expected**: 소속: "operations"
6. **Expected**: 권한 범위 태그 2개 — bot:read, data:read
7. **Expected**: 액션: "재활성화", "폐기" 버튼 표시 (정지 버튼 없음)

## 9. Agent 멤버 — revoked 카드 (old-agent-01)

1. old-agent-01 카드 확인
2. **Expected**: 카드 전체 반투명 스타일
3. **Expected**: 아바타 🐺 (반투명)
4. **Expected**: ID: "old-agent-01" (흐린 텍스트), 이름: "구 리서치 에이전트"
5. **Expected**: 상태 뱃지 "revoked" (빨간색/negative)
6. **Expected**: 소속: "default"
7. **Expected**: 액션 버튼 없음

## 10. Agent 멤버 — 상태 필터

1. "active" 탭 클릭
2. **Expected**: active 상태 에이전트 4개만 표시 (strategy-dev-01, strategy-dev-02, risk-monitor, treasury-agent)
3. "suspended" 탭 클릭
4. **Expected**: suspended 상태 에이전트 1개만 표시 (ops-agent-01)
5. "revoked" 탭 클릭
6. **Expected**: revoked 상태 에이전트 1개만 표시 (old-agent-01)
7. "전체" 탭 클릭
8. **Expected**: 6개 에이전트 모두 표시

## 11. Agent 멤버 — 소속 필터

1. 소속 셀렉트에서 "strategy-lab" 선택
2. **Expected**: strategy-lab 소속 에이전트만 표시 (strategy-dev-01, strategy-dev-02)
3. 소속 셀렉트에서 "전체 소속" 선택
4. **Expected**: 모든 에이전트 표시

## 12. 에이전트 등록 — 모달 열기

1. "+ 에이전트 등록" 버튼 클릭
2. **Expected**: 등록 모달 표시
3. **Expected**: 모달 타이틀 "에이전트 등록"
4. **Expected**: 폼 필드 4개
   - Agent ID: 텍스트 입력, 힌트 "영문, 숫자, 하이픈만 사용 가능"
   - 이름: 텍스트 입력
   - 소속 (org): 셀렉트 — default, strategy-lab, risk, treasury, operations
   - 권한 범위 (Scopes): 체크박스 9개 — strategy:read, strategy:write, report:write, approval:create, approval:review, bot:read, data:read, data:write, backtest:run
5. **Expected**: "취소", "등록" 버튼 표시

## 13. 에이전트 등록 — 취소

1. 폼에 Agent ID "test-agent" 입력
2. "취소" 버튼 클릭
3. **Expected**: 모달이 닫힘
4. **Expected**: Agent 목록에 "test-agent"가 추가되지 않음

## 14. 에이전트 등록 — 제출 및 토큰 발급

1. "+ 에이전트 등록" 버튼 클릭 → 모달 열기
2. Agent ID: "strategy-dev-03" 입력
3. 이름: "전략 리서치 3호" 입력
4. 소속: "strategy-lab" 선택
5. 권한 범위: strategy:write, data:read, backtest:run, report:write 체크
6. "등록" 버튼 클릭
7. **Expected**: 등록 모달이 닫히고 토큰 표시 모달이 열림

## 15. 에이전트 등록 — 토큰 표시 모달

1. 토큰 표시 모달 확인
2. **Expected**: 모달 타이틀 "✓ 에이전트 등록 완료" (파란색/positive)
3. **Expected**: Agent ID "strategy-dev-03" 표시
4. **Expected**: 발급된 토큰이 모노스페이스 박스에 표시
5. **Expected**: 경고 배너 "⚠ 이 토큰은 다시 표시되지 않습니다. 안전한 곳에 복사해 두세요." (노란색)
6. **Expected**: "토큰 복사", "닫기" 버튼 표시

## 16. 에이전트 등록 — 토큰 복사 및 닫기

1. "토큰 복사" 버튼 클릭
2. **Expected**: 클립보드에 토큰이 복사됨
3. "닫기" 버튼 클릭
4. **Expected**: 모달이 닫힘
5. **Expected**: Agent 목록에 "strategy-dev-03" 카드가 추가됨

## 17. 에이전트 상세 — 페이지 진입

1. strategy-dev-01 카드 클릭
2. **Expected**: `/members/{id}` 상세 페이지로 이동
3. **Expected**: 헤더에 "← 에이전트 관리" 뒤로가기 링크 + "strategy-dev-01" 타이틀

## 18. 에이전트 상세 — 헤더 정보

1. 상세 헤더 확인
2. **Expected**: 타이틀 "strategy-dev-01"
3. **Expected**: "active" 뱃지 (파란색/positive) + "strategy-lab" 뱃지 (회색/muted) + "전략 리서치 1호" 텍스트
4. **Expected**: 우측에 "정지" 버튼 + "폐기" 버튼 (빨간색)

## 19. 에이전트 상세 — 기본 정보 카드

1. "기본 정보" 카드 확인
2. **Expected**: 4개 항목 표시
   - Agent ID: "strategy-dev-01" (모노스페이스)
   - 이름: "전략 리서치 1호"
   - 소속: "strategy-lab"
   - 상태: "active" 뱃지 (파란색/positive)

## 20. 에이전트 상세 — 활동 정보 카드

1. "활동 정보" 카드 확인
2. **Expected**: 4개 항목 표시
   - 생성일: "2026-02-15 10:00"
   - 생성자: "owner"
   - 마지막 활동: "2026-03-13 09:30"
   - 정지 시각: "-" (활성 상태이므로)

## 21. 에이전트 상세 — 토큰 관리

1. "토큰 관리" 섹션 확인
2. **Expected**: 토큰 접두어 "ante_ak_****" (모노스페이스) 표시
3. **Expected**: "토큰 재발급" 버튼 표시
4. **Expected**: 경고 힌트 "⚠ 토큰 재발급 시 기존 토큰이 즉시 무효화됩니다." (노란색)

## 22. 에이전트 상세 — 권한 범위 표시

1. "권한 범위 (Scopes)" 섹션 확인
2. **Expected**: 섹션 우측에 "편집" 버튼 표시
3. **Expected**: 현재 권한 태그 표시 — strategy:read, strategy:write, report:write, data:read, backtest:run

## 23. 에이전트 상세 — 권한 범위 편집

1. "편집" 버튼 클릭
2. **Expected**: 권한 태그 아래에 편집 영역 토글 표시 (구분선 포함)
3. **Expected**: 체크박스 9개 표시 — 현재 부여된 권한은 체크됨, 미부여 권한은 체크 해제
4. **Expected**: "저장", "취소" 버튼 표시

## 24. 에이전트 상세 — 권한 편집 취소

1. 체크박스 변경 (예: approval:create 체크)
2. "취소" 버튼 클릭
3. **Expected**: 편집 영역이 닫힘
4. **Expected**: 권한 태그가 변경 전 상태 유지

## 25. 에이전트 상세 — 권한 편집 저장

1. "편집" 버튼 클릭
2. approval:create 체크박스 추가 체크
3. "저장" 버튼 클릭
4. **Expected**: 편집 영역이 닫힘
5. **Expected**: 권한 태그에 "approval:create"가 추가됨

## 26. 에이전트 상세 — 뒤로가기

1. "← 에이전트 관리" 링크 클릭
2. **Expected**: `/members` 페이지로 이동
