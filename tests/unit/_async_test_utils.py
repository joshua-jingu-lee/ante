"""``asyncio.run`` mock 용 공유 테스트 helper (#1980).

일부 CLI 테스트는 ``rows = asyncio.run(_coro())`` 형태의 인라인 coroutine
생성부를 ``patch("asyncio.run")`` 으로 가로채 반환값만 단언한다. 이때
``mock_run.return_value = X`` 만 두면 mock 이 넘어온 coroutine 을
await/close 하지 않아 GC 시점에 ``RuntimeWarning: coroutine ... was never
awaited`` + ``PytestUnraisableExceptionWarning`` 이 발생한다(#1897 zero-warning
기준 위반).

:func:`asyncio_run_returning` 은 ``side_effect`` 팩토리로, 넘어온 coroutine 을
명시적으로 close 해 해당 경고를 막고 지정한 값을 반환한다.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def asyncio_run_returning(value: Any) -> Callable[..., Any]:
    """``patch("asyncio.run")`` 용 ``side_effect`` 팩토리(#1980).

    반환된 함수는 첫 인자로 받은 coroutine 을 ``close()`` 하여
    'coroutine was never awaited' 경고를 막고 ``value`` 를 반환한다.
    ``-W error::RuntimeWarning`` 하에서도 동작하도록 coroutine 을 확실히 닫는다.
    """

    def _run(coro: Any = None, *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutine(coro):
            coro.close()
        return value

    return _run
