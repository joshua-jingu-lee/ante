"""``create_app`` 미들웨어 등록 순서 회귀 테스트 (#1403).

spec SSOT: ``docs/specs/web-api/02-design-decisions.md`` "인증 게이트 단계" +
"CORS 설정" 절. Starlette ``add_middleware()`` 는 ``insert(0)`` 시맨틱이므로
**마지막 add가 가장 바깥** (요청을 가장 먼저 받음)이다.

의도된 요청 처리 순서:
    ``TokenAuth → RequireAuth → Audit → CORS → 라우트``

이를 위한 add 호출 순서 (역순):
    1. CORSMiddleware
    2. AuditMiddleware
    3. RequireAuthMiddleware
    4. TokenAuthMiddleware

``app.user_middleware`` 는 ``insert(0)`` 결과 add **역순** 으로 저장되므로
``[TokenAuth, RequireAuth, Audit, CORS]`` 순서를 가진다.

본 테스트는 위 spec 매핑을 코드 상수로 고정해 잘못된 등록 순서 (예:
``TokenAuth`` 가 ``RequireAuth`` 앞에 add 되어 Bearer caller 부착 전 default-deny
가 발화하는 회귀) 가 들어와도 즉시 실패하게 한다.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from ante.web.app import create_app  # noqa: E402
from ante.web.middleware import (  # noqa: E402
    AuditMiddleware,
    RequireAuthMiddleware,
    TokenAuthMiddleware,
)


def _middleware_classes(app: object) -> list[type]:
    """``app.user_middleware`` 에 등록된 미들웨어 클래스 리스트."""
    return [m.cls for m in app.user_middleware]  # type: ignore[attr-defined]


class TestMiddlewareOrderWithoutFrontend:
    """frontend 빌드 미존재 분기 (SPAFallbackMiddleware 미부착)."""

    def test_user_middleware_order_default(self) -> None:
        """등록 순서: ``TokenAuth → RequireAuth → Audit → CORS`` (user_middleware 시점).

        spec 02-design-decisions.md "add_middleware 순서 vs 실행 순서":
        마지막 add 가 list 가장 앞으로 가서 가장 바깥에 위치한다.
        """
        app = create_app()
        classes = _middleware_classes(app)

        # SPAFallbackMiddleware 가 추가될 수도 있으므로 위 4개 미들웨어만
        # 추출해서 상대 순서를 비교한다.
        target = {
            TokenAuthMiddleware,
            RequireAuthMiddleware,
            AuditMiddleware,
            CORSMiddleware,
        }
        observed = [c for c in classes if c in target]
        assert observed == [
            TokenAuthMiddleware,
            RequireAuthMiddleware,
            AuditMiddleware,
            CORSMiddleware,
        ]

    def test_token_auth_added_after_require_auth(self) -> None:
        """``TokenAuthMiddleware`` 는 ``RequireAuthMiddleware`` 보다 **나중에** add 되어
        야 한다 (= 더 바깥, 더 먼저 실행).

        spec 02-design-decisions.md "CORS 등록 순서와 RequireAuth의 관계" 절:
        반대로 add 하면 Bearer caller 가 부착되기 전에 default-deny 가 발화해
        **정상 Bearer 토큰 사용자도 모두 401** 을 받는 회귀가 발생한다.
        """
        app = create_app()
        classes = _middleware_classes(app)
        # user_middleware 는 LIFO add 결과 역순으로 저장.
        # TokenAuth 가 RequireAuth 보다 **앞**에 와야 더 바깥이다.
        token_idx = classes.index(TokenAuthMiddleware)
        require_idx = classes.index(RequireAuthMiddleware)
        assert token_idx < require_idx

    def test_cors_added_first(self) -> None:
        """``CORSMiddleware`` 는 가장 안쪽 (마지막 실행).

        Starlette LIFO 시맨틱: 가장 먼저 add → user_middleware list 끝으로 감
        → 빌드 시 reversed → 가장 안쪽.
        """
        app = create_app()
        classes = _middleware_classes(app)
        # CORS 가 RequireAuth/Audit/Token 보다 **뒤**에 있어야 한다.
        cors_idx = classes.index(CORSMiddleware)
        require_idx = classes.index(RequireAuthMiddleware)
        audit_idx = classes.index(AuditMiddleware)
        token_idx = classes.index(TokenAuthMiddleware)
        assert cors_idx > require_idx
        assert cors_idx > audit_idx
        assert cors_idx > token_idx


class TestMiddlewareOrderWithFrontend:
    """frontend 빌드 존재 분기 (SPAFallbackMiddleware 부착).

    ``_mount_frontend`` 가 SPAFallbackMiddleware 를 추가로 add 하지만, 인증
    관련 4개 미들웨어의 상대 순서는 유지되어야 한다.

    Codex 권장 (3 보강): SPAFallback 존재/부재 두 케이스 모두 회귀 보호.
    """

    def test_relative_order_preserved_with_spa_fallback(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPAFallbackMiddleware 추가 시에도 인증 4단 상대 순서 유지."""
        from pathlib import Path

        # frontend dist 디렉토리를 가짜로 만들어 _mount_frontend 분기를 활성화.
        fake_dist = Path(str(tmp_path)) / "dist"
        fake_dist.mkdir(parents=True)
        (fake_dist / "index.html").write_text("<html></html>")

        # _get_frontend_dir 가 fake_dist 를 반환하도록 monkeypatch.
        from ante.web import app as app_module

        monkeypatch.setattr(app_module, "_get_frontend_dir", lambda: fake_dist)

        app = create_app()
        classes = _middleware_classes(app)

        # SPAFallbackMiddleware 가 추가됐는지 확인.
        spa_classes = [c for c in classes if c.__name__ == "SPAFallbackMiddleware"]
        assert spa_classes, "SPAFallbackMiddleware 가 등록되어야 한다"

        # 인증 4단 상대 순서 검증.
        token_idx = classes.index(TokenAuthMiddleware)
        require_idx = classes.index(RequireAuthMiddleware)
        audit_idx = classes.index(AuditMiddleware)
        cors_idx = classes.index(CORSMiddleware)
        assert token_idx < require_idx < audit_idx < cors_idx
