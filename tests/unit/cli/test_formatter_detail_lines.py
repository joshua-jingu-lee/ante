"""``detail_lines``가 dict를 키·값 줄로 펼친다 (#2884)."""

from __future__ import annotations

from ante.cli.formatter import detail_lines


def test_scalar_values_pad_key_to_width() -> None:
    assert detail_lines({"id": "a1", "count": 0, "flag": False}) == [
        "  id             : a1",
        "  count          : 0",
        "  flag           : False",
    ]


def test_dict_value_gets_header_and_key_equals_value_lines() -> None:
    assert detail_lines({"params": {"bot_id": "bot-1", "qty": 3}}) == [
        "  params         :",
        "    bot_id = bot-1",
        "    qty = 3",
    ]


def test_list_value_gets_header_and_dash_lines() -> None:
    assert detail_lines({"fields": ["a", "b"]}) == [
        "  fields         :",
        "    - a",
        "    - b",
    ]


def test_list_of_dicts_joins_key_equals_value() -> None:
    assert detail_lines({"history": [{"action": "created", "actor": "m"}]}) == [
        "  history        :",
        "    - action=created, actor=m",
    ]


def test_empty_values_emit_no_line() -> None:
    assert detail_lines({"a": None, "b": "", "c": [], "d": {}, "e": "x"}) == [
        "  e              : x",
    ]


def test_width_argument_changes_key_padding() -> None:
    assert detail_lines({"id": "a1"}, width=4) == ["  id  : a1"]


def test_empty_mapping_yields_no_lines() -> None:
    assert detail_lines({}) == []
