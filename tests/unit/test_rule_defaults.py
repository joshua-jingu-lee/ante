"""``ante.rule.defaults.resolve_effective_rules`` 단위 테스트.

회귀: A7 oracle (#1296) — KIS 모의투자 KRX 장종료 상태에 시장가 매수 신호가
``RuleEngineManager``의 default ``trading_hours`` 미주입으로 인해 broker까지
도달했다. 본 helper는 broker_type별 default와 stored override를 merge한다.
"""

from __future__ import annotations

from ante.account.models import Account
from ante.rule.defaults import resolve_effective_rules


def _make_account(broker_type: str, account_id: str = "domestic") -> Account:
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="KRX",
        currency="KRW",
        broker_type=broker_type,
    )


def test_resolve_effective_rules_kis_domestic_default_only() -> None:
    """KIS domestic + stored=None → default ``trading_hours``가 자동 주입된다."""
    account = _make_account("kis-domestic")

    effective = resolve_effective_rules(account, None)

    assert effective == [{"type": "trading_hours", "enabled": True}]


def test_resolve_effective_rules_kis_domestic_empty_stored_injects_default() -> None:
    """KIS domestic + 빈 stored 리스트 → default 동일하게 주입."""
    account = _make_account("kis-domestic")

    effective = resolve_effective_rules(account, [])

    assert effective == [{"type": "trading_hours", "enabled": True}]


def test_resolve_effective_rules_kis_domestic_explicit_disable() -> None:
    """stored에서 ``trading_hours``를 ``enabled: false``로 명시 비활성화하면
    default 주입 없이 stored 그대로 유지된다 (Agent가 24h 테스트 모드 등을
    명시적으로 켤 수 있어야 함)."""
    account = _make_account("kis-domestic")
    stored = [{"type": "trading_hours", "enabled": False}]

    effective = resolve_effective_rules(account, stored)

    # default 추가 없이 stored 단일 항목만 남아야 한다.
    assert effective == [{"type": "trading_hours", "enabled": False}]


def test_resolve_effective_rules_kis_domestic_explicit_override_with_options() -> None:
    """stored에 ``trading_hours``가 추가 파라미터와 함께 있으면 default를
    override한다 (중복되지 않는다)."""
    account = _make_account("kis-domestic")
    stored = [
        {
            "type": "trading_hours",
            "enabled": True,
            "start_time": "09:30",
            "end_time": "15:00",
        }
    ]

    effective = resolve_effective_rules(account, stored)

    # 같은 type은 stored 1건만 — default가 추가로 들어가면 안 된다.
    assert len(effective) == 1
    assert effective[0]["start_time"] == "09:30"
    assert effective[0]["end_time"] == "15:00"


def test_resolve_effective_rules_test_broker_no_default() -> None:
    """test broker는 default rule이 없다. stored가 None이면 빈 리스트."""
    account = _make_account("test")

    assert resolve_effective_rules(account, None) == []


def test_resolve_effective_rules_test_broker_preserves_stored() -> None:
    """test broker도 stored가 있으면 그대로 통과한다."""
    account = _make_account("test")
    stored = [{"type": "daily_loss_limit", "max_daily_loss_percent": 0.05}]

    effective = resolve_effective_rules(account, stored)

    assert effective == stored


def test_resolve_effective_rules_preserves_custom_rules() -> None:
    """KIS + stored에 default와 다른 custom type → default + custom 둘 다 유지."""
    account = _make_account("kis-domestic")
    stored = [
        {"type": "daily_loss_limit", "max_daily_loss_percent": 0.05},
    ]

    effective = resolve_effective_rules(account, stored)

    types = [r.get("type") for r in effective]
    assert types == ["trading_hours", "daily_loss_limit"]


def test_resolve_effective_rules_unknown_broker_type_no_default() -> None:
    """등록되지 않은 broker_type은 default 없이 stored 그대로 통과."""
    account = _make_account("unknown-broker")
    stored = [{"type": "daily_loss_limit"}]

    effective = resolve_effective_rules(account, stored)

    assert effective == stored


def test_resolve_effective_rules_ignores_non_dict_stored_entries_for_dedup() -> None:
    """stored에 non-dict 잡음이 들어와도 type-key 기반 중복 검사가 안전하게
    동작한다 (default가 잘못 사라지지 않는다)."""
    account = _make_account("kis-domestic")
    # 첫 항목은 무효 (string). 두 번째 항목은 정상 custom rule.
    stored = [
        "garbage",  # type: ignore[list-item]
        {"type": "daily_loss_limit", "max_daily_loss_percent": 0.05},
    ]

    effective = resolve_effective_rules(account, stored)  # type: ignore[arg-type]

    types = [r.get("type") for r in effective if isinstance(r, dict)]
    # default trading_hours가 보존되고 + custom + (passthrough된 garbage)
    assert "trading_hours" in types
    assert "daily_loss_limit" in types
