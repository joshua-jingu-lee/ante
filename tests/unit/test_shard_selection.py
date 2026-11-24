"""단위 테스트 샤드 분할과 샤드 목록 검사의 성질 (#2786)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_shards() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_test_shards.py"
    spec = importlib.util.spec_from_file_location("check_test_shards", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shard check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shards = _load_shards()


def _unit_test_files() -> list[str]:
    unit = REPO_ROOT / "tests" / "unit"
    paths = {*unit.rglob("test_*.py"), *unit.rglob("*_test.py")}
    return sorted(path.relative_to(REPO_ROOT).as_posix() for path in paths)


FILES = _unit_test_files()


def test_repository_has_unit_test_files():
    assert len(FILES) > 100
    assert "tests/unit/test_shard_selection.py" in FILES


@pytest.mark.parametrize("total", range(1, 9))
def test_every_file_lands_in_exactly_one_shard(total):
    buckets: dict[int, list[str]] = {i: [] for i in range(1, total + 1)}
    for path in FILES:
        index = shards.shard_of(path, total)
        assert 1 <= index <= total
        buckets[index].append(path)
    flattened = sorted(p for bucket in buckets.values() for p in bucket)
    assert flattened == FILES


def test_one_shard_takes_everything():
    assert {shards.shard_of(path, 1) for path in FILES} == {1}


def test_assignment_is_deterministic():
    first = [shards.shard_of(path, 4) for path in FILES]
    assert first == [shards.shard_of(path, 4) for path in FILES]
    # crc32는 프로세스와 무관한 고정값이다(hash()와 다르다). 3511400577 % 4 == 1.
    assert shards.shard_of("tests/unit/test_account.py", 4) == 2
    assert shards.shard_of("tests/unit/test_account.py", 7) == 7


CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _ci_shard_matrix() -> list[object]:
    data = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return list(data["jobs"]["test-shard"]["strategy"]["matrix"]["shard"])


def test_ci_shard_matrix_is_one_to_n():
    matrix = _ci_shard_matrix()
    assert matrix == list(range(1, len(matrix) + 1))


def test_largest_shard_is_at_most_twice_the_mean():
    total = len(_ci_shard_matrix())
    counts = [0] * total
    for path in FILES:
        counts[shards.shard_of(path, total) - 1] += 1
    assert min(counts) > 0
    assert max(counts) <= 2 * len(FILES) / total


@pytest.mark.parametrize("value", ["1/1", "1/4", "4/4", "3/8"])
def test_parse_shard_accepts(value):
    index, total = shards.parse_shard(value)
    assert f"{index}/{total}" == value


@pytest.mark.parametrize(
    "value", ["0/4", "5/4", "a/b", "1/0", "0/0", "1", "1/4/2", " 1/4", "-1/4", ""]
)
def test_parse_shard_rejects(value):
    with pytest.raises(ValueError):
        shards.parse_shard(value)


def test_resolve_manifest_anchors_a_relative_path_at_the_base(tmp_path):
    resolved = shards.resolve_manifest("out/test-shard-1.txt", tmp_path)
    assert resolved == tmp_path / "out" / "test-shard-1.txt"
    assert resolved.is_absolute()


def test_resolve_manifest_keeps_an_absolute_path(tmp_path):
    target = tmp_path / "elsewhere" / "test-shard-1.txt"
    assert shards.resolve_manifest(str(target), tmp_path / "base") == target


# ── 샤드 목록 검사 (fail-closed) ─────────────────────────────────────────

COLLECT_OUTPUT = """\
tests/unit/test_a.py::test_one
tests/unit/test_a.py::test_two
tests/unit/sub/test_b.py::test_x[1]
tests/unit/sub/test_b.py::test_x[2]

4 tests collected in 0.10s
"""


def _run(
    tmp_path: Path,
    lists: dict[str, list[str]],
    *,
    collected: str = COLLECT_OUTPUT,
    total: str = "2",
    skip_coverage: tuple[str, ...] = (),
    extra_coverage: tuple[str, ...] = (),
) -> int:
    collect = tmp_path / "collect.txt"
    collect.write_text(collected, encoding="utf-8")
    manifest_dir = tmp_path / "artifacts"
    manifest_dir.mkdir()
    for name, ids in lists.items():
        (manifest_dir / name).write_text(
            "".join(f"{i}\n" for i in ids), encoding="utf-8"
        )
        data = name.replace("test-shard-", "coverage-shard-").replace(".txt", ".data")
        if data not in skip_coverage:
            (manifest_dir / data).write_bytes(b"")
    for data in extra_coverage:
        (manifest_dir / data).write_bytes(b"")
    return shards.main(
        [
            "--shards",
            total,
            "--collected",
            str(collect),
            "--manifest-dir",
            str(manifest_dir),
        ]
    )


GOOD = {
    "test-shard-1.txt": [
        "tests/unit/test_a.py::test_one",
        "tests/unit/test_a.py::test_two",
    ],
    "test-shard-2.txt": [
        "tests/unit/sub/test_b.py::test_x[1]",
        "tests/unit/sub/test_b.py::test_x[2]",
    ],
}


def test_check_passes_on_a_partition(tmp_path, capsys):
    assert _run(tmp_path, GOOD) == 0
    out = capsys.readouterr().out
    assert "OK: 2 shards ran 4 tests == 4 collected" in out
    assert "2 coverage files" in out


def test_check_fails_when_a_coverage_file_is_missing(tmp_path, capsys):
    assert _run(tmp_path, GOOD, skip_coverage=("coverage-shard-2.data",)) == 1
    out = capsys.readouterr().out
    assert "expected 2 coverage files, found 1" in out
    assert "expected 2 shard lists" not in out


def test_check_fails_when_there_are_more_coverage_files_than_shards(tmp_path, capsys):
    assert _run(tmp_path, GOOD, extra_coverage=("coverage-shard-3.data",)) == 1
    out = capsys.readouterr().out
    assert "expected 2 coverage files, found 3" in out
    assert "expected 2 shard lists" not in out


def test_check_fails_when_a_list_is_missing(tmp_path, capsys):
    assert _run(tmp_path, {"test-shard-1.txt": GOOD["test-shard-1.txt"]}) == 1
    assert "expected 2 shard lists, found 1" in capsys.readouterr().out


def test_check_fails_on_a_duplicate(tmp_path, capsys):
    lists = dict(
        GOOD,
        **{
            "test-shard-2.txt": [
                *GOOD["test-shard-2.txt"],
                "tests/unit/test_a.py::test_one",
            ]
        },
    )
    assert _run(tmp_path, lists) == 1
    assert "1 test(s) ran in more than one shard" in capsys.readouterr().out


def test_check_fails_on_a_missing_test(tmp_path, capsys):
    lists = dict(GOOD, **{"test-shard-2.txt": GOOD["test-shard-2.txt"][:1]})
    assert _run(tmp_path, lists) == 1
    assert "  - tests/unit/sub/test_b.py::test_x[2]" in capsys.readouterr().out


def test_check_fails_on_an_unknown_test(tmp_path, capsys):
    lists = dict(
        GOOD,
        **{"test-shard-2.txt": [*GOOD["test-shard-2.txt"], "tests/unit/test_c.py::t"]},
    )
    assert _run(tmp_path, lists) == 1
    assert "  + tests/unit/test_c.py::t" in capsys.readouterr().out


def test_check_fails_on_an_empty_collected_list(tmp_path, capsys):
    assert _run(tmp_path, {}, collected="no tests ran\n", total="2") == 1
    assert "collected list is empty" in capsys.readouterr().out


@pytest.mark.parametrize("total", ["", "0", "x", "+2", "2_0", " 2", "2\n", "\u0662"])
def test_check_fails_on_a_bad_shard_count(tmp_path, total):
    assert _run(tmp_path, GOOD, total=total) == 1


def test_check_fails_when_the_collected_file_is_absent(tmp_path, capsys):
    manifest_dir = tmp_path / "artifacts"
    manifest_dir.mkdir()
    code = shards.main(
        [
            "--shards",
            "1",
            "--collected",
            str(tmp_path / "nope.txt"),
            "--manifest-dir",
            str(manifest_dir),
        ]
    )
    assert code == 1
    assert "collected list not found" in capsys.readouterr().out
