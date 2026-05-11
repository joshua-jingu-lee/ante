"""DynamicConfigService 단위 테스트."""

import pytest

from ante.config import ConfigError, DynamicConfigService
from ante.config.dynamic import _is_value_finite, validate_value
from ante.core import Database
from ante.eventbus.events import ConfigChangedEvent


class FakeEventBus:
    """테스트용 EventBus 대역."""

    def __init__(self):
        self.published: list = []

    async def publish(self, event):
        self.published.append(event)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return FakeEventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = DynamicConfigService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


async def test_set_and_get(service):
    """동적 설정을 저장하고 조회한다."""
    await service.set("rule.max_daily_loss_rate", 0.03, category="rule")
    value = await service.get("rule.max_daily_loss_rate")
    assert value == 0.03


async def test_get_missing_raises(service):
    """존재하지 않는 키는 ConfigError."""
    with pytest.raises(ConfigError, match="Dynamic config not found"):
        await service.get("nonexistent")


async def test_get_missing_with_default(service):
    """default가 있으면 예외 대신 반환."""
    value = await service.get("nonexistent", default=42)
    assert value == 42


async def test_set_publishes_event(service, eventbus):
    """설정 변경 시 ConfigChangedEvent를 발행한다."""
    await service.set("key", "value", category="test")

    assert len(eventbus.published) == 1
    event = eventbus.published[0]
    assert isinstance(event, ConfigChangedEvent)
    assert event.key == "key"
    assert event.category == "test"


async def test_set_overwrites(service):
    """같은 키에 다시 설정하면 덮어쓴다."""
    await service.set("k", 1, category="c")
    await service.set("k", 2, category="c")
    assert await service.get("k") == 2


async def test_get_by_category(service):
    """카테고리별 조회."""
    await service.set("rule.a", 1, category="rule")
    await service.set("rule.b", 2, category="rule")
    await service.set("fund.c", 3, category="fund")

    rules = await service.get_by_category("rule")
    assert len(rules) == 2
    assert rules["rule.a"] == 1
    assert rules["rule.b"] == 2


async def test_exists(service):
    """존재 여부 확인."""
    assert not await service.exists("x")
    await service.set("x", 1, category="c")
    assert await service.exists("x")


async def test_delete(service):
    """설정 삭제."""
    await service.set("x", 1, category="c")
    assert await service.delete("x")
    assert not await service.exists("x")


async def test_delete_nonexistent(service):
    """존재하지 않는 키 삭제 시 False."""
    assert not await service.delete("nonexistent")


async def test_json_complex_types(service):
    """복합 JSON 타입 저장/복원."""
    await service.set("list_val", [1, 2, 3], category="test")
    assert await service.get("list_val") == [1, 2, 3]

    await service.set("dict_val", {"a": 1}, category="test")
    assert await service.get("dict_val") == {"a": 1}


# ── #1379 oracle A7: system.log_level 서비스 경계 검증 ────────────────


async def test_set_invalid_log_level_raises_value_error(service, eventbus):
    """invalid system.log_level 값은 ValueError 로 거부된다 (서비스 경계).

    IPC/CLI/web 어느 경로든 서비스 경계를 통과하지 못해야 한다 — oracle
    probe 가 보낸 ``ORACLE_INVALID_LEVEL`` 같은 값이 dynamic_config 와
    history 에 영구 저장되는 경로를 차단한다.
    """
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", "ORACLE_INVALID_LEVEL", category="system")

    # 영속/이벤트 사이드이펙트가 발생하지 않아야 한다.
    assert not await service.exists("system.log_level")
    assert eventbus.published == []


async def test_set_valid_log_level_succeeds(service, eventbus):
    """``_VALID_LOG_LEVELS`` 멤버(대문자) 값은 그대로 통과한다."""
    await service.set("system.log_level", "DEBUG", category="system")
    assert await service.get("system.log_level") == "DEBUG"
    assert len(eventbus.published) == 1


async def test_set_unknown_key_no_validation_succeeds(service):
    """invariant 가 정의되지 않은 키는 generic CRUD 동작 그대로 통과."""
    # 임의 string/dict/list 모두 통과해야 generic 동작이 유지된다.
    await service.set("any.unknown.key", "anything", category="misc")
    assert await service.get("any.unknown.key") == "anything"

    await service.set("another.unknown", {"complex": [1, 2]}, category="misc")
    assert await service.get("another.unknown") == {"complex": [1, 2]}


async def test_set_lowercase_log_level_raises_value_error(service, eventbus):
    """대소문자 정책: 소문자 ``"debug"`` 는 거부 (대소문자 구분, #1379)."""
    with pytest.raises(ValueError, match="대소문자 구분"):
        await service.set("system.log_level", "debug", category="system")

    assert not await service.exists("system.log_level")
    assert eventbus.published == []


async def test_set_non_string_log_level_raises_value_error(service, eventbus):
    """문자열이 아닌 값(숫자/None 등)도 거부."""
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", 10, category="system")
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", None, category="system")

    assert not await service.exists("system.log_level")
    assert eventbus.published == []


# ── #1412 oracle A7: numeric finite invariant (write + read) ──────────────


class TestValidateValueFiniteNumeric:
    """``validate_value`` 의 generic numeric finite 가드 (#1412).

    write 경계에서 NaN/Infinity/-Infinity 를 거부해야 한다. 이 가드는 키와
    무관하게 적용되어 IPC/CLI/web 모든 경로에서 동일하게 동작한다.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "risk.max_mdd_pct",
            "anything.else",
            "rule.max_daily_loss_rate",
            "completely_unknown_key",
        ],
    )
    @pytest.mark.parametrize(
        "value",
        [float("nan"), float("inf"), float("-inf")],
    )
    def test_validate_value_rejects_non_finite_numeric(self, key, value):
        """NaN/Infinity/-Infinity 는 모든 키에서 거부된다."""
        with pytest.raises(ValueError, match="finite"):
            validate_value(key, value)

    @pytest.mark.parametrize(
        "value",
        [0.1, 0, -1, 1.5, -100.0, 1e10, -1e-10],
    )
    def test_validate_value_accepts_finite_numeric(self, value):
        """finite numeric 값은 통과한다 (회귀 보존)."""
        # 임의 키로 호출해도 generic 가드가 통과.
        validate_value("risk.max_mdd_pct", value)

    def test_validate_value_bool_excluded_true(self):
        """bool True 는 numeric 가드에서 명시 제외된다.

        Python 에서 ``isinstance(True, int)`` 는 True 이지만 ``True`` 는
        finite (1) 이므로 의도치 않게 거부되어선 안 된다.
        """
        validate_value("any.bool.key", True)

    def test_validate_value_bool_excluded_false(self):
        """bool False 도 numeric 가드에서 명시 제외된다."""
        validate_value("any.bool.key", False)

    @pytest.mark.parametrize(
        "value",
        ["not-numeric", "NaN", "Infinity", None, [], {}, ["nested"]],
    )
    def test_validate_value_non_numeric_passes(self, value):
        """numeric 이 아닌 값은 generic 가드 무영향 (회귀 보존).

        invariant 가 정의되지 않은 키에서는 string/None/list/dict 모두 통과.
        ``system.log_level`` 같은 키별 검증은 별도 분기에서 처리된다.
        """
        validate_value("anything", value)


async def test_set_rejects_nan_at_service_boundary(service, eventbus):
    """``service.set`` 가 NaN 을 ValueError 로 거부한다 (#1412)."""
    with pytest.raises(ValueError, match="finite"):
        await service.set("risk.max_mdd_pct", float("nan"), category="risk")

    # 영속/이벤트 사이드이펙트가 발생하지 않아야 한다.
    assert not await service.exists("risk.max_mdd_pct")
    assert eventbus.published == []


async def test_set_rejects_inf_at_service_boundary(service, eventbus):
    """``service.set`` 가 Infinity 를 ValueError 로 거부한다 (#1412)."""
    with pytest.raises(ValueError, match="finite"):
        await service.set("risk.max_mdd_pct", float("inf"), category="risk")
    with pytest.raises(ValueError, match="finite"):
        await service.set("risk.max_mdd_pct", float("-inf"), category="risk")

    assert not await service.exists("risk.max_mdd_pct")
    assert eventbus.published == []


async def test_set_accepts_finite_numeric_regression(service):
    """정상 finite numeric 값은 그대로 저장된다 (회귀 보존, #1412)."""
    await service.set("risk.max_mdd_pct", 0.1, category="risk")
    assert await service.get("risk.max_mdd_pct") == 0.1


async def _insert_legacy_value(service, key: str, raw_json: str, category: str) -> None:
    """DB 에 직접 raw JSON row 를 삽입 (legacy NaN row 시뮬레이션).

    ``service.set`` 는 finite 가드를 통과시키므로 NaN row 를 만들 수 없다.
    legacy 시나리오를 재현하기 위해 db 를 직접 호출한다.
    """
    await service._db.execute(
        """INSERT INTO dynamic_config (key, value, category, updated_at)
           VALUES (?, ?, ?, datetime('now'))""",
        (key, raw_json, category),
    )


async def test_get_raises_on_legacy_nan_row(service):
    """legacy NaN row 가 DB 에 있으면 ``get`` 이 ConfigError 로 격리한다 (#1412).

    SQLite 에 직접 ``"NaN"`` JSON 을 삽입한 뒤 ``json.loads`` 가 복원하는
    ``float('nan')`` 가 그대로 downstream 으로 흘러가는 것을 read 경계가
    막아야 한다.
    """
    await _insert_legacy_value(service, "risk.max_mdd_pct", "NaN", "risk")

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get("risk.max_mdd_pct")


async def test_get_raises_on_legacy_infinity_row(service):
    """legacy Infinity row 도 read 경계에서 ConfigError 로 격리된다 (#1412)."""
    await _insert_legacy_value(service, "rule.threshold", "Infinity", "rule")

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get("rule.threshold")


async def test_get_returns_finite_numeric_regression(service):
    """정상 finite 값은 ``get`` 이 그대로 반환한다 (회귀 보존, #1412)."""
    await service.set("risk.max_mdd_pct", 0.1, category="risk")
    assert await service.get("risk.max_mdd_pct") == 0.1


async def test_get_all_raises_on_legacy_nan_row(service):
    """``get_all`` 도 legacy NaN row 에서 ConfigError (#1412)."""
    await _insert_legacy_value(service, "risk.max_mdd_pct", "NaN", "risk")
    await service.set("risk.other", 0.05, category="risk")

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get_all()


async def test_get_by_category_raises_on_legacy_nan_row(service):
    """``get_by_category`` 도 legacy NaN row 에서 ConfigError (#1412)."""
    await _insert_legacy_value(service, "risk.max_mdd_pct", "NaN", "risk")

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get_by_category("risk")


async def test_get_all_returns_finite_values_regression(service):
    """normal seed 만 있을 때 ``get_all`` 이 정상 동작 (회귀 보존, #1412)."""
    await service.set("risk.max_mdd_pct", 0.1, category="risk")
    await service.set("rule.threshold", 5, category="rule")
    await service.set("flag.enabled", True, category="flag")
    await service.set("name.label", "hello", category="meta")

    items = await service.get_all()
    by_key = {item["key"]: item["value"] for item in items}
    assert by_key["risk.max_mdd_pct"] == 0.1
    assert by_key["rule.threshold"] == 5
    assert by_key["flag.enabled"] is True
    assert by_key["name.label"] == "hello"


async def test_set_self_heals_over_legacy_nan_row(service, eventbus):
    """legacy NaN row 를 정상 finite 값으로 덮어쓰는 self-healing 허용 (#1412).

    Non-Goals 인 자동 cleanup 과는 별개로, 사용자가 ``set`` 으로 정상 값을
    써넣는 정상 lifecycle 은 막히지 않아야 한다. ``get`` 의 read defense 가
    ConfigError 를 raise 하더라도 ``set`` 은 ``old_value=None`` 으로 진행한다.
    """
    await _insert_legacy_value(service, "risk.max_mdd_pct", "NaN", "risk")

    # ConfigError 가 새어 나오면 안 된다.
    await service.set("risk.max_mdd_pct", 0.1, category="risk")

    # 덮어쓰기 성공 — 다시 get 하면 정상 값 반환.
    assert await service.get("risk.max_mdd_pct") == 0.1

    # 이벤트 1개(정상 set) 발행.
    assert len(eventbus.published) == 1
    event = eventbus.published[0]
    assert event.key == "risk.max_mdd_pct"


# ── #1412 P2-1 회귀: nested dict/list non-finite 검사 ─────────────────────


class TestValidateValueNestedFinite:
    """nested ``dict``/``list`` 내부 float 도 재귀적으로 finite 검사 (#1412 P2-1).

    이전 구현은 top-level scalar 만 검사하여 ``{"threshold": NaN}`` 같은
    dict 값이 통과되었다. ``_is_value_finite`` helper 가 컨테이너 내부까지
    재귀 검사함을 보장한다.
    """

    def test_dict_with_nan_value_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.params", {"threshold": float("nan")})

    def test_dict_with_inf_value_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.params", {"threshold": float("inf")})

    def test_dict_with_negative_inf_value_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.params", {"threshold": float("-inf")})

    def test_dict_with_mixed_values_rejects_on_first_nan(self):
        """정상 값과 NaN 이 섞이면 NaN 으로 인해 거부된다."""
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.params", {"threshold": 0.1, "limit": float("nan")})

    def test_list_with_nan_element_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.list", [0.1, float("nan"), 0.5])

    def test_list_with_inf_element_rejected(self):
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.list", [float("inf")])

    def test_deeply_nested_dict_nan_rejected(self):
        """2단계 이상 중첩된 dict 내부도 재귀 검사된다."""
        with pytest.raises(ValueError, match="finite"):
            validate_value("risk.nested", {"outer": {"inner": float("nan")}})

    def test_list_of_dicts_with_nan_rejected(self):
        """list 안의 dict 안의 NaN 도 거부된다."""
        with pytest.raises(ValueError, match="finite"):
            validate_value(
                "risk.tiers",
                [{"name": "a", "value": 0.1}, {"name": "b", "value": float("nan")}],
            )

    def test_dict_with_finite_values_passes(self):
        """정상 nested dict 는 통과한다 (회귀 보존)."""
        validate_value("risk.params", {"threshold": 0.1, "limit": 0.5})

    def test_nested_dict_with_finite_values_passes(self):
        validate_value("risk.params", {"outer": {"inner": 0.1, "other": 2}})

    def test_list_of_finite_floats_passes(self):
        validate_value("risk.list", [0.1, 0.2, 0.5])

    def test_helper_bool_in_dict_passes(self):
        """bool 은 dict 안에서도 finite 검사에서 제외된다."""
        ok, _bad = _is_value_finite({"flag": True, "other_flag": False})
        assert ok

    def test_helper_string_in_container_passes(self):
        """str/None 은 numeric 이 아니므로 통과 (회귀 보존)."""
        ok, _bad = _is_value_finite({"name": "alpha", "missing": None, "list": ["x"]})
        assert ok

    def test_helper_returns_first_violating_value(self):
        """헬퍼가 violating float 자체를 함께 반환한다 (오류 메시지 진단성)."""
        bad_value = float("inf")
        ok, bad = _is_value_finite({"a": 0.1, "b": bad_value, "c": float("nan")})
        assert not ok
        # dict 순회 순서상 b 가 먼저이므로 bad 는 inf.
        assert bad == bad_value


async def test_set_rejects_nested_nan_at_service_boundary(service, eventbus):
    """``service.set`` 가 nested NaN dict 를 ValueError 로 거부한다 (#1412 P2-1)."""
    with pytest.raises(ValueError, match="finite"):
        await service.set(
            "risk.params", {"threshold": float("nan"), "limit": 0.5}, category="risk"
        )

    # 영속/이벤트 사이드이펙트가 없어야 한다.
    assert not await service.exists("risk.params")
    assert eventbus.published == []


async def test_set_rejects_nested_inf_list_at_service_boundary(service, eventbus):
    """``service.set`` 가 list 안의 Infinity 도 거부한다 (#1412 P2-1)."""
    with pytest.raises(ValueError, match="finite"):
        await service.set("risk.tiers", [0.1, float("inf"), 0.5], category="risk")

    assert not await service.exists("risk.tiers")
    assert eventbus.published == []


async def test_get_raises_on_legacy_nested_nan_row(service):
    """legacy nested NaN dict row 가 ``get`` 에서 ConfigError 로 격리된다 (#1412 P2-1).

    legacy row 가 ``{"threshold": NaN}`` 형태로 DB 에 들어있는 경우 read 경계
    helper 가 컨테이너 내부까지 재귀 검사하여 격리해야 한다.
    """
    # SQLite 에 직접 nested NaN JSON 을 넣는다. json.dumps 는 NaN 을 그대로
    # 직렬화하므로 raw 문자열을 구성한다.
    await _insert_legacy_value(
        service,
        "risk.params",
        '{"threshold": NaN, "limit": 0.5}',
        "risk",
    )

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get("risk.params")


async def test_get_raises_on_legacy_nested_infinity_list_row(service):
    """legacy list 안의 Infinity row 도 read 경계에서 격리된다 (#1412 P2-1)."""
    await _insert_legacy_value(
        service,
        "risk.tiers",
        "[0.1, Infinity, 0.5]",
        "risk",
    )

    with pytest.raises(ConfigError, match="non-finite"):
        await service.get("risk.tiers")


async def test_set_accepts_nested_finite_regression(service):
    """정상 nested finite 값은 그대로 저장/조회된다 (회귀 보존, #1412 P2-1)."""
    payload = {"threshold": 0.1, "limit": 0.5, "label": "ok", "flag": True}
    await service.set("risk.params", payload, category="risk")
    assert await service.get("risk.params") == payload


# ── #1412 P2-2 회귀: 큰 정수 OverflowError 방지 ──────────────────────────


class TestValidateValueLargeInt:
    """``int`` 는 finite 검사에서 제외된다 (#1412 P2-2).

    Python ``int`` 는 임의 정밀도이며 NaN/Infinity 를 표현할 수 없다. 이전
    구현은 ``isinstance(value, (int, float))`` 후 ``math.isfinite(value)`` 를
    호출해 매우 큰 정수에서 ``OverflowError`` 가 발생, finite 정수의 저장/조회가
    500 으로 깨졌다.
    """

    def test_validate_value_large_positive_int_passes(self):
        validate_value("foo.bar", 10**500)

    def test_validate_value_large_negative_int_passes(self):
        validate_value("foo.bar", -(10**500))

    def test_validate_value_int_in_dict_passes(self):
        validate_value("foo.bar", {"big": 10**500, "neg": -(10**400)})

    def test_validate_value_int_in_list_passes(self):
        validate_value("foo.bar", [10**500, -(10**400), 0, 1])


async def test_set_accepts_large_int(service):
    """``service.set`` 이 임의 정밀도 정수를 정상 저장한다 (#1412 P2-2)."""
    big = 10**500
    await service.set("foo.bar", big, category="x")
    assert await service.get("foo.bar") == big


async def test_set_accepts_large_negative_int(service):
    """음수 큰 정수도 정상 처리된다 (#1412 P2-2)."""
    big = -(10**500)
    await service.set("foo.neg", big, category="x")
    assert await service.get("foo.neg") == big


async def test_set_accepts_nested_large_int(service):
    """dict/list 안의 큰 정수도 통과한다 (#1412 P2-1 + P2-2)."""
    payload = {"big": 10**500, "items": [10**400, -(10**400), 1]}
    await service.set("foo.nested", payload, category="x")
    assert await service.get("foo.nested") == payload
