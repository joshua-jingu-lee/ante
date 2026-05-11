"""``require_scope`` factory 단위 테스트 (#1406).

본 테스트는 ``src/ante/web/deps.py`` 의 ``require_scope`` factory 와 4개
module-level alias (``require_audit_read`` / ``require_config_write`` /
``require_report_write`` / ``require_strategy_write``) 가 다음 invariant 를
유지하는지 검증한다.

INV1 — marker 부착 (#1405 정적 회귀 보존):
    4개 alias 와 factory 가 만드는 임의 dependency 모두에
    ``_is_authentication_dependency = True`` 가 부착되어 있다.

INV2 — detail 매핑 byte-exact (외부 API 응답 무변경):
    ``_SCOPE_DENIED_DETAIL_MAP`` 이 4개 scope 의 기존 detail 상수를 그대로
    참조한다. 특히 ``audit:read`` 는 "master" 단어 없는 특수 case 가 보존됨.

INV3 — default 템플릿:
    ``_SCOPE_DENIED_DETAIL_MAP`` 에 없는 scope 에 대해 default 템플릿이 사용되고,
    템플릿이 ``master`` / ``human`` / 해당 ``scope`` 문자열을 모두 포함한다.

INV4 — alias identity 보존 (Depends() cache invariant):
    각 alias 는 module import 시 한 번만 평가되어 동일 객체로 캐싱된다.
    동일 module 을 다시 import 해도 같은 객체를 반환한다.

INV5 — alias __name__ (디버깅 가독성):
    factory 가 생성한 dependency 의 ``__name__`` 이 scope 기반으로 부여된다.

403 응답 detail byte-exact regression 은 기존 회귀 테스트
(``tests/unit/test_require_audit_read.py``, ``tests/unit/test_web_api.py``,
``tests/unit/test_runtime_mutation_auth.py``) 가 라우트 통합 경로로 보장한다.
"""

from __future__ import annotations

from ante.web.deps import (
    _AUDIT_READ_PERMISSION_DENIED_DETAIL,
    _CONFIG_WRITE_PERMISSION_DENIED_DETAIL,
    _REPORT_WRITE_PERMISSION_DENIED_DETAIL,
    _SCOPE_DENIED_DETAIL_MAP,
    _STRATEGY_WRITE_PERMISSION_DENIED_DETAIL,
    _default_denied_detail,
    require_audit_read,
    require_config_write,
    require_report_write,
    require_scope,
    require_strategy_write,
)

# ── INV1: marker 부착 ──────────────────────────────────────────────────────


def test_4_aliases_have_authentication_marker() -> None:
    """4개 module-level alias 모두 ``_is_authentication_dependency`` marker 부착."""
    for alias in (
        require_audit_read,
        require_config_write,
        require_report_write,
        require_strategy_write,
    ):
        assert getattr(alias, "_is_authentication_dependency", False), (
            f"{alias.__name__} 에 _is_authentication_dependency marker 가 누락됨 "
            "(#1405 회귀: test_route_auth_coverage 가 marker 없음으로 보고)"
        )


def test_factory_attaches_marker_to_new_scope() -> None:
    """factory 가 만드는 임의 dependency 도 marker 부착되어야 (#1407 후속)."""
    custom = require_scope("bot:read")
    assert getattr(custom, "_is_authentication_dependency", False), (
        "require_scope factory 가 inner_dep 에 marker 를 부착해야 한다 "
        "(신규 scope alias 가 추가되면 자동으로 #1405 정적 검증을 통과해야 함)"
    )


# ── INV2: detail 매핑 byte-exact ────────────────────────────────────────────


def test_4_scopes_detail_map_byte_exact() -> None:
    """``_SCOPE_DENIED_DETAIL_MAP`` 이 4개 scope 의 기존 상수를 byte-exact
    참조한다. 매핑 변경은 외부 API 응답 회귀로 이어지므로 즉시 차단."""
    assert (
        _SCOPE_DENIED_DETAIL_MAP["audit:read"] == _AUDIT_READ_PERMISSION_DENIED_DETAIL
    )
    assert (
        _SCOPE_DENIED_DETAIL_MAP["config:write"]
        == _CONFIG_WRITE_PERMISSION_DENIED_DETAIL
    )
    assert (
        _SCOPE_DENIED_DETAIL_MAP["report:write"]
        == _REPORT_WRITE_PERMISSION_DENIED_DETAIL
    )
    assert (
        _SCOPE_DENIED_DETAIL_MAP["strategy:write"]
        == _STRATEGY_WRITE_PERMISSION_DENIED_DETAIL
    )


def test_audit_read_detail_has_no_master_word() -> None:
    """``audit:read`` detail 은 "master" 단어 없는 특수 case (spec
    predicate 는 동일하지만 사용자 메시지가 history 상 master 를 언급하지
    않는다). 이 invariant 가 깨지면 외부 API 응답 회귀."""
    assert "master" not in _AUDIT_READ_PERMISSION_DENIED_DETAIL


def test_other_3_scopes_detail_has_master_word() -> None:
    """``config:write`` / ``report:write`` / ``strategy:write`` detail 은
    "master, human 멤버 또는 ... scope" 패턴을 따른다."""
    for detail in (
        _CONFIG_WRITE_PERMISSION_DENIED_DETAIL,
        _REPORT_WRITE_PERMISSION_DENIED_DETAIL,
        _STRATEGY_WRITE_PERMISSION_DENIED_DETAIL,
    ):
        assert "master" in detail
        assert "human" in detail
        assert "scope" in detail


# ── INV3: default 템플릿 ────────────────────────────────────────────────────


def test_default_denied_detail_contains_required_tokens() -> None:
    """``_default_denied_detail`` 템플릿은 ``master`` / ``human`` / 입력 scope /
    ``scope`` 문자열을 모두 포함한다 (신규 scope 알림 일관성)."""
    detail = _default_denied_detail("bot:read")
    assert "master" in detail
    assert "human" in detail
    assert "bot:read" in detail
    assert "scope" in detail


def test_default_template_for_unknown_scope() -> None:
    """``_SCOPE_DENIED_DETAIL_MAP`` 에 없는 scope 는 default 템플릿이 사용된다.

    factory 내부에서 사용하는 ``_SCOPE_DENIED_DETAIL_MAP.get(scope) or
    _default_denied_detail(scope)`` 분기를 직접 흉내내어 검증한다.
    """
    unknown_scope = "ledger:write"
    assert unknown_scope not in _SCOPE_DENIED_DETAIL_MAP
    selected = _SCOPE_DENIED_DETAIL_MAP.get(unknown_scope) or _default_denied_detail(
        unknown_scope
    )
    assert selected == _default_denied_detail(unknown_scope)
    assert unknown_scope in selected


# ── INV4: alias identity 보존 ───────────────────────────────────────────────


def test_aliases_are_singletons_across_reimports() -> None:
    """모듈 재 import 시 같은 alias 객체가 반환된다 (Depends() instance cache
    가 깨지지 않음).

    Python module cache (``sys.modules``) 가 같은 객체를 캐싱하므로 같은
    이름의 alias 는 반드시 동일 identity 를 유지한다.
    """
    from ante.web import deps as deps_a
    from ante.web import deps as deps_b

    assert deps_a.require_audit_read is deps_b.require_audit_read
    assert deps_a.require_config_write is deps_b.require_config_write
    assert deps_a.require_report_write is deps_b.require_report_write
    assert deps_a.require_strategy_write is deps_b.require_strategy_write


# ── INV5: alias __name__ ───────────────────────────────────────────────────


def test_factory_dependency_name_is_scope_based() -> None:
    """factory 가 만드는 dependency 의 ``__name__`` 이 scope 기반으로 부여
    되어 디버깅 가독성을 유지한다."""
    assert require_scope("audit:read").__name__ == "require_scope_audit_read"
    assert require_scope("config:write").__name__ == "require_scope_config_write"
    assert require_scope("bot:read").__name__ == "require_scope_bot_read"
