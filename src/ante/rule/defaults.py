"""Account broker_type별 default rule 해석 helper.

스펙(`docs/specs/rule-engine/09-rule-management.md` "Stored rules vs effective
rules")에 따라, RuleEngine에 적용되는 effective rule은 다음 두 source의
type-key 기반 merge다.

- broker_type별 system defaults (예: ``kis-domestic``은 ``trading_hours``
  자동 포함)
- ``accounts.{account_id}.rules`` DynamicConfig의 explicit overrides

stored 항목이 default와 같은 ``type``이면 stored가 default를 override한다.
사용자/Agent는 ``enabled: false``로 default를 명시 비활성화할 수 있다.

회귀: A7 oracle (#1296) — KIS 모의투자 KRX 장종료 상태에서 시장가 매수
신호가 매 interval 반복 → broker까지 도달 → KIS ``40580000`` 4건 누적.
근본 원인은 ``RuleEngineManager``가 KIS domestic 계좌에 default
``TradingHoursRule``을 자동 주입하지 않아 spec(09-rule-management.md L43)
위반이었다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.account.models import Account


# broker_type → list of default rule config dicts.
# rule config 스키마는 RuleEngine._create_rule이 받는 형태와 동일하다
# (``type`` 필수, 나머지는 Rule 서브클래스 ``__init__`` config로 전달).
_DEFAULT_RULES_BY_BROKER_TYPE: dict[str, list[dict[str, Any]]] = {
    "kis-domestic": [{"type": "trading_hours", "enabled": True}],
    "test": [],  # test broker는 24h 거래
}


def resolve_effective_rules(
    account: Account,
    stored_rules: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Account broker_type별 default + stored explicit override를 merge.

    정책:

    - ``stored_rules``에 ``type``이 같은 항목이 있으면 그것이 default를
      override한다 (``enabled: false``로 비활성화 포함).
    - ``stored_rules``에 default ``type``이 없으면 default를 effective에
      추가한다.
    - ``stored_rules``의 추가 항목(custom rule)은 그대로 유지한다.

    Args:
        account: 대상 계좌. ``broker_type``만 default 결정에 쓴다.
        stored_rules: ``accounts.{account_id}.rules`` DynamicConfig에서
            읽은 explicit override 리스트. ``None``은 빈 리스트와 동일.

    Returns:
        RuleEngine.load_rules_from_config()에 그대로 넘길 수 있는 effective
        rule config 리스트.
    """
    defaults = _DEFAULT_RULES_BY_BROKER_TYPE.get(account.broker_type, [])
    overrides = stored_rules or []
    override_types = {r.get("type") for r in overrides if isinstance(r, dict)}
    result: list[dict[str, Any]] = []
    for d in defaults:
        if d.get("type") not in override_types:
            result.append(d)
    result.extend(overrides)
    return result
