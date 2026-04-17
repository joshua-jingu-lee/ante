# Member 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 개요

Member 모듈은 **Ante 시스템에서 행위를 수행하는 모든 주체(사람·AI)를 등록·인증·관리하는 모듈**이다.
Ante의 "회사" 메타포에서 대표(사용자)와 직원(AI Agent)은 모두 Member로 관리되며, 시스템 내의 모든 행위는 member_id로 추적된다.

**핵심 원칙:**
- 시스템의 모든 행위자는 반드시 등록된 Member여야 한다.
- Member는 `human`과 `agent` 두 가지 타입으로 분류되며, 타입별로 인증 방식이 분리된다.
- `master` 역할은 `human` 타입에만 부여할 수 있다. **agent는 어떤 경우에도 master가 될 수 없다.**
- master는 시스템에 정확히 1명만 존재한다.

**주요 기능:**
- **Member 등록/관리**: master가 agent 멤버를 등록·비활성화·폐기
- **인증**: 타입별 분리된 토큰 체계 (human key / agent key)
- **권한 제어**: 역할 기반 접근 제어 (RBAC)
- **감사 추적**: 모든 행위를 member_id로 기록
- **비밀번호 복구**: Recovery Key 기반 자체 완결형 복구
