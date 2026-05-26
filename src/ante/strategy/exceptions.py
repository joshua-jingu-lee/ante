"""Strategy 모듈 예외.

class-level ``code`` 정책 (#1843 sub-PR 6, 실측 mirror):

- ``StrategyNotFoundError`` → ``STRATEGY_NOT_FOUND`` (#1796 lock 보존)
- ``StrategyLoadError`` → ``STRATEGY_LOAD_ERROR`` (validation; 본 PR 신규 부여)
- ``StrategyValidationError`` → ``STRATEGY_VALIDATION_ERROR`` (validation; 본 PR
  신규 부여) — CLI ``strategy submit``/``validate`` 의
  ``STRATEGY_VALIDATION_ERROR`` surface 와 동일 안정 코드 SSOT.
- ``StrategyFileAccessError`` → ``STRATEGY_FILE_ACCESS_ERROR`` (external; 본 PR
  신규 부여) — 파일 시스템 접근 실패.
- ``IncompatibleExchangeError`` → ``STRATEGY_INCOMPATIBLE_EXCHANGE`` (validation;
  본 PR 신규 부여) — 전략 exchange ↔ 계좌 exchange 비호환 거부.

``StrategyError`` base 는 의도적으로 ``.code`` 를 부여하지 않는다 — 사용
사례가 없으며, allowlist 의 ``pending_migration`` baseline 으로 보존된다
(#1842 ``AccountError`` 와 동일 패턴).
"""


class StrategyError(Exception):
    """Strategy 기본 예외."""

    pass


class StrategyNotFoundError(StrategyError):
    """전략을 찾을 수 없음 (#1796).

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``getattr(e, "code", "EXECUTION_ERROR")``로 안정 코드
    ``"STRATEGY_NOT_FOUND"`` 를 노출하도록 한다. ``StrategyRegistry.update_status``
    가 missing strategy 에 대해 raise 하면 CLI ``strategy set-status`` 가
    typed code envelope 으로 종료한다.
    """

    code: str = "STRATEGY_NOT_FOUND"


class StrategyLoadError(StrategyError):
    """전략 파일 로드 실패 (#1843 sub-PR 6).

    클래스 레벨 ``code`` 는 IPC 서버 ``getattr(e, "code", ...)`` 와 helper
    registry-first lookup 이 동일 ``STRATEGY_LOAD_ERROR`` 안정 코드를 surface
    하도록 정렬한다. CLI ``strategy submit`` 의 load 단계 envelope (
    ``stage="load"`` / ``code="STRATEGY_LOAD_ERROR"``) 와 동일 SSOT.
    """

    code: str = "STRATEGY_LOAD_ERROR"


class StrategyValidationError(StrategyError):
    """전략 검증 실패 (#1843 sub-PR 6).

    클래스 레벨 ``code`` 는 CLI ``strategy submit``/``validate`` /
    ``strategy list --status`` 의 ``STRATEGY_VALIDATION_ERROR`` surface 와
    동일 안정 코드 SSOT. ``StrategyError`` 의 ``getattr(e, "code", ...)``
    fallback 경로가 본 typed 코드를 envelope 에 노출한다.
    """

    code: str = "STRATEGY_VALIDATION_ERROR"


class StrategyFileAccessError(StrategyError):
    """전략 파일 접근 오류 (#1843 sub-PR 6).

    클래스 레벨 ``code`` 는 파일 시스템 접근 실패의 안정 코드 surface 다.
    taxonomy 카테고리는 ``external`` (파일 시스템은 외부 의존성).
    """

    code: str = "STRATEGY_FILE_ACCESS_ERROR"


class IncompatibleExchangeError(StrategyError):
    """전략의 exchange와 계좌의 exchange가 호환되지 않음 (#1843 sub-PR 6).

    클래스 레벨 ``code`` 는 전략 ↔ 계좌 호환성 검증 거부의 안정 코드 다.
    taxonomy 카테고리는 ``validation`` (호환성 invariant 위반).
    """

    code: str = "STRATEGY_INCOMPATIBLE_EXCHANGE"
