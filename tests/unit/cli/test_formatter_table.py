"""``OutputFormatter.table`` 의 출력 바이트를 고정한다 (#2751).

``table`` 을 쓰는 명령 호출부 여러 곳이 같은 text를 내야 하므로, 표의
text를 만드는 부분을 바꾸는 동안 이 리터럴은 한 글자도 바뀌지 않아야 한다.
"""

from __future__ import annotations

from typing import Any

import pytest

from ante.cli.formatter import OutputFormatter, table_lines

_ROWS: list[dict[str, Any]] = [
    {"id": "a", "name": "알파", "qty": 1},
    {"id": "bravo-long-identifier", "qty": 22.5},
    {"id": "", "name": None, "qty": 0},
]


def _table(mode: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    OutputFormatter(mode).table(rows, columns)


class TestTableText:
    def test_empty_rows(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("text", [], ["id", "name"])
        assert capsys.readouterr().out == "(no data)\n"

    def test_rows_and_widths(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("text", _ROWS, ["id", "name", "qty"])
        assert capsys.readouterr().out == (
            "          id |         name |          qty\n"
            "------------------------------------------\n"
            "           a |           알파 |            1\n"
            "bravo-long-identifier |              |         22.5\n"
            "             |         None |            0\n"
        )

    def test_single_column(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("text", [{"x": "v"}], ["x"])
        assert capsys.readouterr().out == ("           x\n------------\n           v\n")

    def test_no_columns(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("text", [{"x": "v"}, {"x": "w"}], [])
        assert capsys.readouterr().out == "\n\n\n\n"


class TestTableJson:
    def test_rows_are_a_bare_array(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("json", [{"id": "a", "qty": 1}], ["id"])
        assert capsys.readouterr().out == (
            '[\n  {\n    "id": "a",\n    "qty": 1\n  }\n]\n'
        )

    def test_empty_rows(self, capsys: pytest.CaptureFixture[str]) -> None:
        _table("json", [], ["id"])
        assert capsys.readouterr().out == "[]\n"


class TestTableLines:
    @pytest.mark.parametrize(
        ("rows", "columns"),
        [([], ["id"]), (_ROWS, ["id", "name", "qty"]), ([{"x": "v"}], ["x"])],
        ids=["empty", "rows", "single"],
    )
    def test_lines_are_the_text_table(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _table("text", rows, columns)
        expected = capsys.readouterr().out
        assert "".join(f"{line}\n" for line in table_lines(rows, columns)) == expected

    def test_empty_rows(self) -> None:
        assert table_lines([], ["id"]) == ["(no data)"]

    def test_header_rule_and_rows(self) -> None:
        assert table_lines([{"a": 1}, {"b": 2}], ["a"]) == [
            "           a",
            "------------",
            "           1",
            "            ",
        ]
