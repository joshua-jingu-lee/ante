"""Config 모듈 예외."""


class ConfigError(Exception):
    """Config 기본 예외."""

    pass


class ConfigValidationError(ValueError):
    """동적 설정 키-invariant 위반 (write 경계 입력 오류).

    ``validate_value`` 에서 ``system.log_level`` 처럼 enum SSOT가 정의된
    키가 invalid 값을 받았을 때 raise된다 (#1673 oracle A7).

    이중 계약 (호출자별 변환):

    - **web**: ``ValueError`` 서브클래스이므로 ``src/ante/web/errors.py`` 의
      글로벌 ``@app.exception_handler(ValueError)`` 가 그대로 잡아 **422**
      로 변환한다 (응답 스키마/거부값 노출 정책은 기존 그대로, 본 이슈
      비목표). **반드시 ``ValueError`` 서브클래스로 유지**해야 한다 —
      기존 service-boundary 테스트(``pytest.raises(ValueError, ...)``)와
      web 422 핸들러가 이 불변조건에 의존한다(비회귀).
    - **IPC**: 서버 ``src/ante/ipc/server.py`` 의 ``except Exception`` 핸들러가
      ``getattr(e, "code", "EXECUTION_ERROR")`` 로 안정 에러코드를 산출한다
      (#1144 S5). ``code`` 클래스 속성을 보유하므로 입력 오류가
      ``EXECUTION_ERROR`` 로 오분류되지 않고 ``CONFIG_VALIDATION_ERROR``
      로 envelope에 노출된다. CLI 클라이언트는 이 코드를 그대로
      ``{status:"error", code, message}`` 로 stdout에 출력한다.
    """

    code = "CONFIG_VALIDATION_ERROR"
