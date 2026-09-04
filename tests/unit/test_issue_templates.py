"""이슈 폼 템플릿과 런북 규범의 대응을 잠그는 테스트 (#2462).

#2462는 두 개의 **전칭 규범**을 문서에 새로 성문화했다.

1. ``docs/runbooks/00-issue-management.md`` §2 Type 표의 **7행 전건**이
   ``.github/ISSUE_TEMPLATE/`` 폼 파일을 가리키고, 각 폼의 ``labels:``가
   같은 행의 ``대응 라벨``과 일치한다.
2. ``docs/runbooks/03-git-workflow.md`` §1.2 하위절이 선언한 라벨 6종
   집합이 ``.agent/commands/autopilot.md`` 「포함 대상」이 열거하는 6종과
   **같은 집합**이다.

집행 장치가 없으면 누군가 폼 파일을 지우거나 이름을 바꾸거나 autopilot의
라벨 집합을 고치는 순간 이 두 규범이 **조용히 거짓**이 되고 CI는 그대로
통과한다. 문서가 스스로를 반증하는 상태로 남는 것이 #2462가 없애려는
바로 그 실패 모드다. 이 저장소는 같은 실패 모드를
``tests/unit/test_generate_cli_reference.py`` 의
``TestAllGeneratorsProvideCheckMode`` 에서 이미 성문화해 뒀다 — 이 파일은
그 선례를 「문서 ↔ 폼」 축에 그대로 적용한다.

**파싱 실패는 통과가 아니라 실패다.** 표 행을 0개 파싱했거나 절 앵커를
찾지 못하면 아래 락이 전부 vacuous pass 하므로, 각 파서는 산출이 비는
즉시 명확한 메시지로 죽는다. 앵커는 매치 횟수까지 확인해 중복·소실
양쪽을 잡는다.

여기서 보지 않는 것: 표 행의 **순서**와 열 문면은
``docs/temp/lock-2462.sh`` 의 L2가 스냅샷으로 잠그고, 이 파일은 그
스냅샷이 만료된 뒤에도 남는 **집합·대응 관계**만 본다. 폼이 GitHub UI에서
실제로 렌더링되는지도 보지 않는다 — 그것은 GitHub의 스키마 검증이 하는
일이고, 여기서는 저장소가 소유한 규범만 잠근다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]

_ISSUE_MANAGEMENT = _REPO_ROOT / "docs" / "runbooks" / "00-issue-management.md"
_GIT_WORKFLOW = _REPO_ROOT / "docs" / "runbooks" / "03-git-workflow.md"
_AUTOPILOT = _REPO_ROOT / ".agent" / "commands" / "autopilot.md"
_TEMPLATE_DIR = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE"

_TEMPLATE_DIR_REL = ".github/ISSUE_TEMPLATE/"

#: §2 Type 표가 담아야 하는 타입 7종. 표에서 파싱한 집합과 대조한다.
_EXPECTED_TYPES = frozenset(
    {"feat", "fix", "refactor", "perf", "docs", "test", "chore"}
)

#: GitHub 이슈 폼이 허용하는 ``body[*].type`` 전체 집합.
_ALLOWED_BODY_TYPES = frozenset(
    {"markdown", "input", "textarea", "dropdown", "checkboxes"}
)

#: 폼 디렉토리에 있어도 표가 가리키지 않아 무방한 파일.
#: ``config.yml``은 폼이 아니라 폼 선택 화면 설정이며 아직 없다(#2462 A2가
#: 후속 이슈로 분리). 나중에 추가돼도 이 락이 헛발동하지 않게 면제한다.
_NON_FORM_FILENAMES = frozenset({"config.yml", "config.yaml"})


def _section(
    text: str,
    start_pattern: str,
    end_pattern: str,
    *,
    source: str,
    what: str,
) -> str:
    """``start_pattern`` 행부터 다음 ``end_pattern`` 행 직전까지를 잘라낸다.

    앵커가 사라지거나 중복되면 락이 엉뚱한 범위를 보거나 아무것도 보지
    않게 되므로, 시작 앵커는 매치 **정확히 1회**를 요구하고 종료 앵커는
    반드시 존재해야 한다.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(start_pattern, line)]
    assert len(starts) == 1, (
        f"{source}에서 {what}의 시작 앵커 /{start_pattern}/ 가 "
        f"{len(starts)}회 매치됐다 — 정확히 1회여야 한다. 앵커가 사라지면 "
        "이 파일의 락이 통째로 vacuous pass 하고, 중복되면 엉뚱한 범위를 "
        "본다."
    )
    start = starts[0]
    ends = [i for i in range(start + 1, len(lines)) if re.match(end_pattern, lines[i])]
    assert ends, (
        f"{source}에서 {what}의 종료 앵커 /{end_pattern}/ 를 찾지 못했다 — "
        "범위가 파일 끝까지 번지면 인접 절의 문장을 이 절의 것으로 오판한다."
    )
    return "\n".join(lines[start : ends[0]])


@dataclass(frozen=True)
class _TypeRow:
    """§2 Type 표의 한 행."""

    type: str
    description: str
    label: str
    form: str

    @property
    def form_path(self) -> Path:
        return _REPO_ROOT / self.form


_TYPE_TABLE_HEADER = "| Type | 설명 | 대응 라벨 | 폼 템플릿 |"

_TYPE_ROW_RE = re.compile(
    r"^\|\s*`(?P<type>[^`|]+)`\s*"
    r"\|\s*(?P<description>[^|]*?)\s*"
    r"\|\s*`(?P<label>[^`|]+)`\s*"
    r"\|\s*`(?P<form>[^`|]+)`\s*\|\s*$"
)


def _parse_type_rows() -> list[_TypeRow]:
    """§2 Type 표(4열)의 행을 파싱한다."""
    section = _section(
        _ISSUE_MANAGEMENT.read_text(encoding="utf-8"),
        r"^## 2\. ",
        r"^## 3\. ",
        source="docs/runbooks/00-issue-management.md",
        what="§2 이슈 제목 컨벤션",
    )
    assert _TYPE_TABLE_HEADER in section, (
        "docs/runbooks/00-issue-management.md §2에서 Type 표 헤더 "
        f"{_TYPE_TABLE_HEADER!r} 를 찾지 못했다. 열 구성이 바뀌면 아래 "
        "전건 대응 락이 행을 하나도 파싱하지 못해 vacuous pass 한다."
    )
    rows: list[_TypeRow] = []
    for line in section.splitlines():
        matched = _TYPE_ROW_RE.match(line)
        if matched is None:
            continue
        rows.append(
            _TypeRow(
                type=matched.group("type"),
                description=matched.group("description"),
                label=matched.group("label"),
                form=matched.group("form"),
            )
        )
    return rows


_TYPE_ROWS = _parse_type_rows()

assert _TYPE_ROWS, (
    "docs/runbooks/00-issue-management.md §2 Type 표에서 행을 하나도 "
    "파싱하지 못했다 (#2462). 이 목록이 비면 아래 폼 대응·스키마 락이 "
    "전부 0회 실행되어 조용히 통과한다 — 그래서 파싱 실패 자체를 실패로 "
    f"둔다. 기대 행 형태: {_TYPE_ROW_RE.pattern}"
)

_for_each_type_row = pytest.mark.parametrize(
    "row",
    _TYPE_ROWS,
    ids=lambda row: row.type,
)


def _load_form(row: _TypeRow) -> dict:
    """표 행이 가리키는 폼 파일을 YAML로 읽는다."""
    assert row.form.startswith(_TEMPLATE_DIR_REL), (
        f"§2 Type 표 `{row.type}` 행의 폼 템플릿 경로 {row.form!r} 가 "
        f"{_TEMPLATE_DIR_REL} 밖을 가리킨다. GitHub은 이 디렉토리만 폼으로 "
        "읽으므로, 다른 경로를 적으면 표가 존재하지 않는 UI 경로를 약속하는 "
        "셈이 된다."
    )
    path = row.form_path
    assert path.is_file(), (
        f"§2 Type 표 `{row.type}` 행이 가리키는 {row.form} 가 없다. "
        "「7행 전건에 폼 템플릿이 있다」가 거짓이 됐다 (#2462) — 파일을 "
        "지웠거나 이름을 바꿨다면 §2 표를 같은 PR에서 함께 고쳐야 한다."
    )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), (
        f"{row.form} 의 최상위가 매핑이 아니다 (실제: {type(data).__name__}). "
        "GitHub 이슈 폼은 최상위 매핑만 받는다."
    )
    return data


def _iter_body_items(row: _TypeRow, form: dict) -> list[dict]:
    """폼의 ``body`` 항목 목록을 얻는다. 비어 있으면 실패한다."""
    body = form.get("body")
    assert isinstance(body, list) and body, (
        f"{row.form} 의 `body`가 비어 있거나 리스트가 아니다 — 입력 필드가 "
        "없는 폼은 UI에서 아무것도 받지 못한다."
    )
    for index, item in enumerate(body):
        assert isinstance(item, dict), (
            f"{row.form} `body[{index}]` 가 매핑이 아니다 "
            f"(실제: {type(item).__name__})."
        )
    return body


class TestTypeTableFormMapping:
    """§2 Type 표 7행 ↔ 폼 파일의 **전건 대응**을 잠근다.

    #2462가 §2에 쓴 「7행 전건에 폼 템플릿이 있다」는 표 안에서 닫히지
    않는 주장이다 — 표는 경로만 적고, 그 경로가 실재하는지와 그 파일이
    같은 행의 `대응 라벨`을 붙이는지는 파일 시스템이 답한다. 이 클래스가
    그 답을 매 CI마다 다시 받아온다.

    행의 **순서**와 설명 문면은 보지 않는다(그쪽은 ``lock-2462.sh`` L2의
    스냅샷 소유). 여기서 보는 것은 집합과 대응 관계뿐이라, 표를 정리하는
    무해한 편집에는 헛발동하지 않으면서 규범이 깨지는 편집은 잡는다.
    """

    def test_table_declares_the_seven_types(self) -> None:
        """표가 타입 7종을 중복 없이 모두 담는다."""
        parsed = [row.type for row in _TYPE_ROWS]
        assert len(parsed) == len(set(parsed)), (
            f"§2 Type 표에 같은 타입이 두 번 나온다: {parsed}. 한 타입이 두 "
            "폼을 가리키면 「그 타입의 이슈를 만들 때 고르는 폼」이 결정되지 "
            "않는다."
        )
        assert set(parsed) == set(_EXPECTED_TYPES), (
            f"§2 Type 표의 타입 집합이 기대와 다르다. 실제={sorted(parsed)} / "
            f"기대={sorted(_EXPECTED_TYPES)}. 타입을 추가·삭제했다면 "
            "03-git-workflow.md §1.2 표와 폼 파일까지 같은 PR에서 함께 "
            "고쳐야 한다."
        )

    @_for_each_type_row
    def test_form_file_exists(self, row: _TypeRow) -> None:
        """표가 가리키는 폼 파일이 실재한다."""
        _load_form(row)

    @_for_each_type_row
    def test_form_labels_match_the_table(self, row: _TypeRow) -> None:
        """폼의 ``labels:``가 같은 행의 `대응 라벨`과 정확히 일치한다.

        폼이 붙이는 라벨이 표와 갈라지면 UI로 등록된 이슈가 표에 없는
        라벨을 달게 되고, autopilot 큐 선별(포함 대상 6종)이 그 이슈를
        예상과 다르게 판정한다.
        """
        form = _load_form(row)
        labels = form.get("labels")
        assert isinstance(labels, list) and labels, (
            f"{row.form} 에 `labels:` 리스트가 없거나 비어 있다 — 폼 경로로 "
            "만든 이슈가 타입 라벨 없이 등록되어 §2가 약속한 라벨 부착이 "
            "일어나지 않는다."
        )
        assert labels == [row.label], (
            f"{row.form} 의 labels={labels!r} 가 §2 Type 표 `{row.type}` 행의 "
            f"대응 라벨 [{row.label!r}] 과 다르다. 한쪽만 고치면 두 문서가 "
            "서로를 부정한다 — §2를 먼저 고치고 폼을 맞춘다."
        )

    def test_template_dir_has_no_orphan_or_missing_form(self) -> None:
        """폼 디렉토리의 파일 집합이 표가 가리키는 집합과 정확히 같다.

        한쪽 방향만 보면 규범이 반쪽만 잠긴다. 표 → 파일만 보면 표에 없는
        **고아 폼**이 UI 목록에 남아 §2 밖의 라벨을 붙이고, 파일 → 표만
        보면 표가 가리키는 폼이 **누락**돼도 통과한다. 그래서 집합 동일성을
        본다.
        """
        present = {
            path.name
            for path in _TEMPLATE_DIR.glob("*.yml")
            if path.name not in _NON_FORM_FILENAMES
        } | {
            path.name
            for path in _TEMPLATE_DIR.glob("*.yaml")
            if path.name not in _NON_FORM_FILENAMES
        }
        declared = {Path(row.form).name for row in _TYPE_ROWS}
        assert present == declared, (
            f"{_TEMPLATE_DIR_REL} 의 폼 파일 집합이 §2 Type 표와 다르다. "
            f"표에 없는 고아 폼={sorted(present - declared)} / "
            f"표만 가리키고 파일이 없는 것={sorted(declared - present)}. "
            f"폼이 아닌 파일은 {sorted(_NON_FORM_FILENAMES)} 만 면제한다."
        )


class TestIssueFormSchema:
    """폼 7종이 GitHub 이슈 폼 스키마와 #2462의 추가 규약을 지키는지 본다.

    스키마 위반은 GitHub UI에서 폼이 **아예 렌더링되지 않는** 형태로
    드러난다 — 그 시점에는 §2가 가리키는 UI 경로가 통째로 죽지만 저장소의
    어떤 검사도 실패하지 않는다. 로컬에서 미리 죽게 만드는 것이 이
    클래스의 일이다.
    """

    @_for_each_type_row
    def test_top_level_keys_present(self, row: _TypeRow) -> None:
        """최상위 ``name``·``description``·``labels``·``title``·``body``가 있다."""
        form = _load_form(row)
        missing = [
            key
            for key in ("name", "description", "labels", "title", "body")
            if not form.get(key)
        ]
        assert not missing, (
            f"{row.form} 에 최상위 키 {missing} 가 없거나 비어 있다. "
            "`title`이 빠지면 §2의 `[{type}] {설명}` 제목 규약이 폼 경로에서 "
            "전혀 집행되지 않고, 나머지가 빠지면 GitHub이 폼을 렌더링하지 "
            "않는다."
        )

    @_for_each_type_row
    def test_title_prefills_the_table_type(self, row: _TypeRow) -> None:
        """``title``이 ``[{type}] `` 프리필이고 그 타입이 표 행과 일치한다.

        §2 제목 컨벤션은 `[{type}] {간결한 설명}`이다. 폼이 제목을
        프리필하지 않으면 UI 경로로 만든 이슈가 타입 토큰 없는 제목을
        갖고, 03-git-workflow.md §1.2 하위절의 갈래 1(제목 토큰으로 prefix
        판정)이 그 이슈에서 작동하지 못한다. 프리필 토큰이 표 행과 다르면
        더 나쁘다 — 라벨과 제목이 서로 다른 타입을 가리킨다.
        """
        form = _load_form(row)
        title = form.get("title")
        assert isinstance(title, str), (
            f"{row.form} 의 `title` 이 문자열이 아니다 (실제: {type(title).__name__})."
        )
        matched = re.match(r"^\[(?P<type>[^\]]+)\] ", title)
        assert matched is not None, (
            f"{row.form} 의 title={title!r} 이 §2 제목 규약 `[{{type}}] ` "
            "형태가 아니다. 여는 대괄호로 시작해 타입 토큰과 닫는 대괄호, "
            "그리고 공백 한 칸이 와야 한다."
        )
        assert matched.group("type") == row.type, (
            f"{row.form} 의 title={title!r} 이 타입 "
            f"`{matched.group('type')}` 을 프리필하는데 §2 Type 표에서 이 "
            f"폼을 가리키는 행은 `{row.type}` 이다. 제목과 라벨이 서로 다른 "
            "타입을 가리키는 이슈가 만들어진다."
        )

    @_for_each_type_row
    def test_body_item_types_are_allowed(self, row: _TypeRow) -> None:
        """``body[*].type``이 GitHub이 허용하는 5종 안에 있다."""
        form = _load_form(row)
        for index, item in enumerate(_iter_body_items(row, form)):
            item_type = item.get("type")
            assert item_type in _ALLOWED_BODY_TYPES, (
                f"{row.form} `body[{index}]` (id={item.get('id')!r}) 의 "
                f"type={item_type!r} 은 허용 집합 "
                f"{sorted(_ALLOWED_BODY_TYPES)} 밖이다 — GitHub이 폼 전체를 "
                "거부한다."
            )

    @_for_each_type_row
    def test_body_items_have_required_attributes(self, row: _TypeRow) -> None:
        """항목마다 ``attributes``가 있고 타입별 필수 키가 채워져 있다.

        ``markdown``은 보여줄 ``value``가, 나머지는 사람이 읽을 ``label``이
        필수다. ``dropdown``·``checkboxes``는 ``options`` 없이는 고를 것이
        없다. 셋 중 하나라도 비면 폼이 렌더링되지 않거나 이름 없는 빈 칸이
        남는다.
        """
        form = _load_form(row)
        for index, item in enumerate(_iter_body_items(row, form)):
            where = f"{row.form} `body[{index}]` (id={item.get('id')!r})"
            attributes = item.get("attributes")
            assert isinstance(attributes, dict), f"{where} 에 `attributes` 매핑이 없다."
            item_type = item.get("type")
            needed = "value" if item_type == "markdown" else "label"
            assert attributes.get(needed), (
                f"{where} 는 type={item_type!r} 이므로 "
                f"`attributes.{needed}` 가 비어 있으면 안 된다."
            )
            if item_type in ("dropdown", "checkboxes"):
                assert attributes.get("options"), (
                    f"{where} 는 type={item_type!r} 인데 "
                    "`attributes.options` 가 비어 있다 — 고를 항목이 없는 "
                    "선택 필드가 된다."
                )

    @_for_each_type_row
    def test_body_ids_are_unique(self, row: _TypeRow) -> None:
        """``id``가 파일 안에서 유일하다.

        중복 ``id``는 GitHub이 폼을 거부하는 사유이자, 이슈 본문에서 어느
        필드의 응답인지 구분할 수 없게 만든다.
        """
        form = _load_form(row)
        ids = [item["id"] for item in _iter_body_items(row, form) if "id" in item]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        assert not duplicates, f"{row.form} 에 중복 `id` 가 있다: {duplicates}"

    @_for_each_type_row
    def test_required_fields_have_no_empty_skeleton_value(self, row: _TypeRow) -> None:
        """required 필드의 ``attributes.value``에 콜론으로 끝나는 행이 없다.

        GitHub은 ``value:`` 프리필을 **사용자 입력으로 인정**한다. 그래서
        required 필드에 ``- 시나리오 1:`` 같은 빈 골격을 프리필해 두면,
        아무것도 안 채운 채 제출해도 required 검증이 통과한다 — 필드를
        required로 둔 의미가 그 자리에서 사라진다. 골격은 ``placeholder:``
        로 옮겨야 한다. ``placeholder``는 회색 힌트일 뿐 제출값이 아니라서
        required가 그대로 살아 있다.

        콜론으로 끝나지 않는 프리필(예: ``- [ ] 단위 테스트 통과`` 같은
        체크리스트)은 프리필 자체가 제출물이므로 그대로 둔다. 판정 기준을
        「콜론으로 끝나는 행」으로 좁힌 이유다.
        """
        form = _load_form(row)
        offenders: list[str] = []
        for item in _iter_body_items(row, form):
            validations = item.get("validations") or {}
            if not isinstance(validations, dict) or not validations.get("required"):
                continue
            attributes = item.get("attributes") or {}
            value = attributes.get("value")
            if not isinstance(value, str):
                continue
            for line in value.splitlines():
                if line.rstrip().endswith(":"):
                    offenders.append(f"id={item.get('id')!r}: {line.strip()!r}")
        assert not offenders, (
            f"{row.form} 의 required 필드에 콜론으로 끝나는 빈 골격 프리필이 "
            f"남아 있다: {offenders}. GitHub이 프리필을 입력으로 인정하므로 "
            "이 상태에서는 required가 무력화된다 — 해당 행을 "
            "`placeholder:` 로 옮겨라."
        )


def _prefix_decision_subsection() -> str:
    """03-git-workflow.md §1.2의 「타입 라벨이 없는 이슈의 prefix 결정」 범위."""
    return _section(
        _GIT_WORKFLOW.read_text(encoding="utf-8"),
        r"^#### 타입 라벨이 없는 이슈의 prefix 결정",
        r"^### ",
        source="docs/runbooks/03-git-workflow.md",
        what="§1.2 「타입 라벨이 없는 이슈의 prefix 결정」 하위절",
    )


class TestPrefixDecisionSubsection:
    """§1.2 하위절이 두 갈래로 닫혀 있고 다른 절의 축을 침범하지 않는지 본다."""

    def test_exactly_two_branches(self) -> None:
        """갈래가 ``1.``·``2.`` 번호 목록 정확히 2개다.

        이 하위절의 결론은 「두 갈래가 산출하는 prefix는 갈래 1의 7종과
        ``chore/`` 뿐」이라는 전칭이다. 갈래가 하나 늘면 그 전칭이 곧바로
        거짓이 되고, 하나 줄면 정의역 일부가 prefix 없이 남는다. 번호를
        모아서 대조하므로 ``1.`` 이 두 번 나오는 형태도 잡는다.
        """
        subsection = _prefix_decision_subsection()
        numbers = [
            line.split(".", 1)[0]
            for line in subsection.splitlines()
            if re.match(r"^[12]\. ", line)
        ]
        assert numbers == ["1", "2"], (
            "§1.2 하위절의 갈래가 번호 목록 `1.`·`2.` 정확히 2개가 아니다 "
            f"(실제: {numbers}). 갈래 수가 바뀌면 하위절 말미의 "
            "「두 갈래가 산출하는 prefix는 …뿐」이라는 전칭이 거짓이 된다."
        )

    @pytest.mark.parametrize(
        "literal",
        ["release/", "epic/", "[epic]", "[release]"],
    )
    def test_no_epic_or_release_literals(self, literal: str) -> None:
        """하위절이 ``release/``·``epic/``·``[epic]``·``[release]``를 쓰지 않는다.

        이 하위절의 정의역은 **타입 라벨이 없는 이슈**이고, 산출은 갈래 1의
        7종 prefix와 ``chore/`` 뿐이다. 여기서 저 리터럴이 나오면 둘 중
        하나가 깨진다.

        - ``epic/``·``[epic]``: 에픽 브랜치는 같은 §1.2 표의 `epic` 행과
          §1.1이 소유한다. 하위절이 에픽을 갈래로 열거하면 같은 절의 표를
          뒤집는다 — 그래서 에픽은 **판정 전 제외**로 올라가 있다.
        - ``release/``·``[release]``: 릴리스는 이슈 축이 아니라 §1.4와
          ``/release prepare``가 소유하는 브랜치 축이다. 게다가
          ``release/`` 는 §3.1 브랜치 리뷰 트리거 글롭 밖이라, 이 하위절이
          그 prefix를 산출하기 시작하면 「이 규칙으로 만든 브랜치는 Gate
          A가 정상 트리거된다」는 마지막 문단이 거짓이 된다.
        """
        subsection = _prefix_decision_subsection()
        assert literal not in subsection, (
            f"§1.2 하위절이 리터럴 {literal!r} 을 포함한다. 이 하위절은 "
            "타입 라벨이 없는 이슈의 prefix만 정하며, 에픽은 §1.2 표의 "
            "`epic` 행과 §1.1이, 릴리스는 §1.4가 소유한다 (#2462 A3)."
        )


_SIX_LABELS_RE = re.compile(r"라벨\s*6종\s*\(([^)]*)\)")
_AUTOPILOT_LABEL_LINE_RE = re.compile(r"^\s*-\s*라벨이\s.*중 하나\s*$")
_BACKTICKED_RE = re.compile(r"`([^`]+)`")


def _subsection_label_set() -> frozenset[str]:
    """§1.2 하위절이 정의역 산정에 쓰는 라벨 6종을 파싱한다."""
    subsection = _prefix_decision_subsection()
    matches = _SIX_LABELS_RE.findall(subsection)
    assert len(matches) == 1, (
        "§1.2 하위절에서 「라벨 6종(…)」 문면을 정확히 1회 찾지 못했다 "
        f"(실제 {len(matches)}회). 이 문면이 그 절의 정의역을 정의하므로, "
        "찾지 못하면 아래 집합 동일성 락이 비교할 대상 자체를 잃는다."
    )
    labels = frozenset(_BACKTICKED_RE.findall(matches[0]))
    assert labels, (
        "§1.2 하위절의 「라벨 6종(…)」 괄호 안에서 백틱 라벨을 하나도 "
        "뽑지 못했다 — 라벨을 백틱으로 감싸 적어야 한다."
    )
    return labels


def _autopilot_label_set() -> frozenset[str]:
    """``autopilot.md`` 「포함 대상」이 열거하는 타입 라벨을 파싱한다."""
    section = _section(
        _AUTOPILOT.read_text(encoding="utf-8"),
        r"^### 포함 대상",
        r"^### ",
        source=".agent/commands/autopilot.md",
        what="「큐 선별 규칙」 → 「포함 대상」 절",
    )
    lines = [
        line for line in section.splitlines() if _AUTOPILOT_LABEL_LINE_RE.match(line)
    ]
    assert len(lines) == 1, (
        ".agent/commands/autopilot.md 「포함 대상」에서 라벨 열거 불릿"
        f"(`- 라벨이 … 중 하나`)을 정확히 1개 찾지 못했다 (실제 "
        f"{len(lines)}개). 이 불릿이 큐 편입 라벨 집합의 정본이다."
    )
    labels = frozenset(_BACKTICKED_RE.findall(lines[0]))
    assert labels, (
        ".agent/commands/autopilot.md 「포함 대상」 라벨 불릿에서 백틱 "
        "라벨을 하나도 뽑지 못했다 — 라벨을 백틱으로 감싸 적어야 한다."
    )
    return labels


class TestLabelSetIdentity:
    """§1.2 하위절 6종 == autopilot 「포함 대상」 6종을 잠근다.

    #2462가 §1.2 하위절에 쓴 「이 6종은 autopilot.md 「포함 대상」이
    열거하는 라벨 집합과 **같은 집합**이다」는 두 파일에 걸친 주장이라,
    어느 한쪽만 고쳐도 조용히 거짓이 된다. 그리고 그 거짓은 눈에 띄지
    않는 방식으로 아프다 — 두 집합이 갈라지면 어떤 이슈는 autopilot 큐에
    편입되면서 동시에 「타입 라벨이 없는 이슈」로 판정돼 prefix 결정
    갈래를 타거나, 반대로 어느 규칙도 다루지 않는 사각지대에 떨어진다.
    """

    def test_subsection_declares_six_labels(self) -> None:
        """하위절이 선언한 라벨이 6종이다."""
        labels = _subsection_label_set()
        assert len(labels) == 6, (
            f"§1.2 하위절이 「라벨 6종」이라 적고 실제로는 {len(labels)}종을 "
            f"열거한다: {sorted(labels)}."
        )

    def test_autopilot_include_labels_match_the_subsection(self) -> None:
        """두 집합이 같다."""
        subsection_labels = _subsection_label_set()
        autopilot_labels = _autopilot_label_set()
        assert subsection_labels == autopilot_labels, (
            "§1.2 하위절의 라벨 집합과 autopilot.md 「포함 대상」의 라벨 "
            "집합이 다르다. "
            f"하위절에만 있음={sorted(subsection_labels - autopilot_labels)} / "
            f"autopilot에만 있음={sorted(autopilot_labels - subsection_labels)}. "
            "한쪽을 고치면 다른 쪽을 같은 PR에서 함께 고쳐야 한다 (#2462)."
        )

    def test_label_set_matches_the_type_table(self) -> None:
        """그 6종이 §2 Type 표 7행의 `대응 라벨` 집합과 같다.

        §1.2 하위절은 이 6종을 「위 표 `대응 라벨` 열의 `feat`~`chore` 7행에
        나오는 라벨」로 **정의**한다. 7행이 6종이 되는 이유는 `feat`·`perf`가
        둘 다 `enhancement`를 쓰기 때문이고, 그 겹침이야말로 §1.2가
        known-limitation으로 선언한 지점이다. 이 락이 없으면 §2 표의 라벨
        하나를 바꿔도 하위절과 autopilot이 옛 집합을 그대로 들고 있으면서
        서로만 일치해 통과한다 — 세 문서를 삼각으로 묶어야 닫힌다.
        """
        table_labels = frozenset(row.label for row in _TYPE_ROWS)
        assert _subsection_label_set() == table_labels, (
            "§1.2 하위절의 라벨 6종이 00-issue-management.md §2 Type 표의 "
            f"`대응 라벨` 집합과 다르다. 하위절={sorted(_subsection_label_set())} / "
            f"§2 표={sorted(table_labels)}."
        )
