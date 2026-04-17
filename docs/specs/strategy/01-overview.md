# Strategy 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 개요

Strategy 모듈은 **전략의 정의·검증·등록·로딩을 담당하는 전략 생명주기 관리 계층**이다.
AI Agent가 생성한 전략 파일을 시스템에 안전하게 통합하기 위한 인터페이스 계약과 검증 절차를 제공하며,
Bot이 전략을 로드하여 실행할 수 있도록 표준화된 전략 인터페이스(ABC, Abstract Base Class)를 정의한다.

**주요 기능**:
- **전략 인터페이스 (ABC)**: Bot이 전략을 실행하기 위한 표준 계약 — 라이프사이클 메서드, 시그널 생성, 메타데이터
- **StrategyContext**: 전략에 노출되는 제한된 API — 데이터 조회, 포트폴리오 조회, 로깅 (직접 시스템 접근 차단)
- **AST(Abstract Syntax Tree) 기반 정적 검증 (StrategyValidator)**: 전략 파일의 안전성·적합성을 코드 실행 없이 검증
- **Strategy Registry**: 검증 완료된 전략 목록 관리 — 등록, 조회, 상태 관리
- **동적 로딩**: importlib 기반 전략 파일 로딩 — `strategies/` 디렉토리에서 런타임 임포트
