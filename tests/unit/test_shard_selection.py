"""단위 테스트 샤드 분할과 샤드 목록 검사의 성질 (#2786)."""

from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess
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


# ── 소요 시간 기록으로 고르게 나누기 (#3036) ─────────────────────────────

RECORD_COUNTS = {f"tests/unit/test_w{i:03d}.py": 3 + i % 7 for i in range(60)}
RECORD_FILES = {
    path: 100 + (i * 37) % 900 for i, path in enumerate(sorted(RECORD_COUNTS))
}
NEW_FILES = {"tests/unit/test_new_a.py": 10, "tests/unit/sub/test_new_b.py": 1}
GONE_FILES = {"tests/unit/test_gone.py": 5000}


def _write_record(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "shard_durations.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _hash_split(counts: dict[str, int], total: int) -> dict[str, int]:
    return {path: shards.shard_of(path, total) for path in counts}


def _loads(
    assignment: dict[str, int], weights: dict[str, int], total: int
) -> list[int]:
    loads = [0] * total
    for path, index in assignment.items():
        loads[index - 1] += weights[path]
    return loads


RECORD_STATES = {
    "normal": (RECORD_COUNTS, RECORD_FILES),
    "with_new_files": ({**RECORD_COUNTS, **NEW_FILES}, RECORD_FILES),
    "with_removed_files": (RECORD_COUNTS, {**RECORD_FILES, **GONE_FILES}),
    "only_removed_files": (RECORD_COUNTS, GONE_FILES),
    "empty_record": (RECORD_COUNTS, {}),
    "no_overlap": (NEW_FILES, RECORD_FILES),
    "no_record": (RECORD_COUNTS, None),
}

BROKEN_RECORDS = {
    "json_error": '{"version": 1, "files": {',
    "wrong_version": {"version": 2, "files": {"tests/unit/test_w000.py": 1}},
    "bool_version": {"version": True, "files": {"tests/unit/test_w000.py": 1}},
    "no_files": {"version": 1},
    "not_an_object": [1, 2],
    "negative": {"version": 1, "files": {"tests/unit/test_w000.py": -1}},
    "float": {"version": 1, "files": {"tests/unit/test_w000.py": 1.5}},
    "string": {"version": 1, "files": {"tests/unit/test_w000.py": "12"}},
    "bool": {"version": 1, "files": {"tests/unit/test_w000.py": True}},
}


@pytest.mark.parametrize("total", range(1, 9))
@pytest.mark.parametrize("state", sorted(RECORD_STATES))
def test_assignment_is_a_partition_for_every_record_state(state, total):
    counts, record = RECORD_STATES[state]
    assignment = shards.assign_shards(counts, record, total)
    assert sorted(assignment) == sorted(counts)
    assert all(1 <= index <= total for index in assignment.values())


@pytest.mark.parametrize("total", range(1, 9))
@pytest.mark.parametrize("name", sorted(BROKEN_RECORDS))
def test_broken_record_falls_back_to_the_hash_split(tmp_path, name, total):
    record = shards.load_record(_write_record(tmp_path, BROKEN_RECORDS[name]))
    assert record is None
    counts = {**RECORD_COUNTS, **NEW_FILES}
    assert shards.assign_shards(counts, record, total) == _hash_split(counts, total)


def test_missing_record_file_loads_as_none(tmp_path):
    assert shards.load_record(tmp_path / "absent.json") is None


@pytest.mark.parametrize(
    "state", ["no_record", "no_overlap", "only_removed_files", "empty_record"]
)
@pytest.mark.parametrize("total", [2, 5, 7])
def test_record_without_overlap_falls_back_to_the_hash_split(state, total):
    counts, record = RECORD_STATES[state]
    assert shards.assign_shards(counts, record, total) == _hash_split(counts, total)


def test_valid_record_round_trips_through_the_loader(tmp_path):
    path = _write_record(tmp_path, {"version": 1, "files": RECORD_FILES})
    assert shards.load_record(path) == RECORD_FILES
    path.write_text(shards.record_text(RECORD_FILES), encoding="utf-8")
    assert shards.load_record(path) == RECORD_FILES


def test_record_text_is_sorted_with_integer_centiseconds():
    text = shards.record_text({"tests/unit/b.py": 2, "tests/unit/a.py": 1})
    assert json.loads(text) == {
        "version": 1,
        "files": {"tests/unit/a.py": 1, "tests/unit/b.py": 2},
    }
    assert text.index("a.py") < text.index("b.py")
    assert text.endswith("\n")


TIED_COUNTS = {f"tests/unit/test_t{i:02d}.py": 4 for i in range(23)}
TIED_RECORD = {path: 50 for path in TIED_COUNTS}


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize(
    ("counts", "record"),
    [
        ({**RECORD_COUNTS, **NEW_FILES}, RECORD_FILES),
        (TIED_COUNTS, TIED_RECORD),
    ],
    ids=["mixed", "all_tied"],
)
def test_assignment_ignores_input_order(counts, record, seed):
    rng = random.Random(seed)
    expected = shards.assign_shards(counts, record, 5)
    keys = list(counts)
    rng.shuffle(keys)
    record_keys = list(record)
    rng.shuffle(record_keys)
    shuffled = shards.assign_shards(
        {k: counts[k] for k in keys}, {k: record[k] for k in record_keys}, 5
    )
    assert shuffled == expected


def test_tied_weights_go_round_robin_by_path_then_shard_number():
    assignment = shards.assign_shards(TIED_COUNTS, TIED_RECORD, 5)
    ordered = sorted(TIED_COUNTS)
    assert [assignment[path] for path in ordered] == [
        i % 5 + 1 for i in range(len(ordered))
    ]


def test_every_shard_job_computes_the_same_split():
    counts = {**RECORD_COUNTS, **NEW_FILES}
    total = 5
    first = shards.assign_shards(dict(counts), dict(RECORD_FILES), total)
    jobs = [shards.assign_shards(counts, RECORD_FILES, total) for _ in range(total)]
    assert all(job == first for job in jobs)


BALANCE_COUNTS = {f"tests/unit/test_b{i:03d}.py": 1 + i % 13 for i in range(300)}
BALANCE_RECORD = {
    path: random.Random(i).randint(50, 3000)
    for i, path in enumerate(sorted(BALANCE_COUNTS))
}


def test_duration_split_is_balanced_where_the_hash_split_is_not():
    total = 5
    weights = shards.file_weights(BALANCE_COUNTS, BALANCE_RECORD)
    assert weights == BALANCE_RECORD
    loads = _loads(
        shards.assign_shards(BALANCE_COUNTS, BALANCE_RECORD, total), weights, total
    )
    assert max(loads) / (sum(loads) / total) <= 1.02
    hashed = _loads(_hash_split(BALANCE_COUNTS, total), weights, total)
    assert max(hashed) / (sum(hashed) / total) > 1.02


def test_new_file_weight_is_its_count_times_the_recorded_rate():
    counts = {**RECORD_COUNTS, **NEW_FILES}
    record = {**RECORD_FILES, **GONE_FILES}
    weights = shards.file_weights(counts, record)
    known_seconds = sum(RECORD_FILES[path] for path in sorted(RECORD_FILES))
    known_count = sum(RECORD_COUNTS[path] for path in sorted(RECORD_COUNTS))
    for path, count in NEW_FILES.items():
        assert weights[path] == count * known_seconds // known_count
    assert "tests/unit/test_gone.py" not in weights
    assert {path: weights[path] for path in RECORD_FILES} == RECORD_FILES


def test_file_weights_is_none_without_overlap():
    assert shards.file_weights(NEW_FILES, RECORD_FILES) is None
    assert shards.file_weights(RECORD_COUNTS, None) is None
    assert shards.file_weights(RECORD_COUNTS, {}) is None


def test_record_path_is_the_fixed_repository_path():
    assert shards.RECORD_PATH == REPO_ROOT / "tests" / "shard_durations.json"


def test_committed_record_is_valid():
    record = shards.load_record(shards.RECORD_PATH)
    assert record is not None, f"invalid or missing record: {shards.RECORD_PATH}"
    assert record
    assert all(type(value) is int and value >= 0 for value in record.values())


def test_committed_record_overlaps_the_unit_test_files():
    record = shards.load_record(shards.RECORD_PATH)
    assert record is not None
    assert set(record) & set(FILES), (
        "the record shares no file with tests/unit — the split would fall back "
        "to the hash; rebuild it with scripts/update_test_shard_durations.py"
    )


# ── 기록 갱신 스크립트 (#3036) ────────────────────────────────────────────


def _load_updater() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "update_test_shard_durations.py"
    spec = importlib.util.spec_from_file_location("update_durations", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load updater: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPDATE_SHARDS = {
    1: {"tests/unit/test_a.py": 120},
    2: {"tests/unit/sub/test_b.py": 30, "tests/unit/test_c.py": 0},
    3: {"tests/unit/test_d.py": 45},
    4: {"tests/unit/test_e.py": 75},
    5: {"tests/unit/test_f.py": 60},
}
UPDATE_COLLECTED = """\
tests/unit/test_a.py::t1
tests/unit/test_a.py::t2
tests/unit/sub/test_b.py::t
tests/unit/test_c.py::t
tests/unit/test_d.py::t
tests/unit/test_e.py::t
tests/unit/test_f.py::t
tests/unit/test_g.py::t

8 tests collected in 0.10s
"""


def _run_updater(tmp_path: Path, files: dict[str, str]) -> tuple[int, Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for name, text in files.items():
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    collected = tmp_path / "collect.txt"
    collected.write_text(UPDATE_COLLECTED, encoding="utf-8")
    output = tmp_path / "out" / "shard_durations.json"
    code = _load_updater().main(
        [
            str(artifacts),
            "--shards",
            "5",
            "--collected",
            str(collected),
            "--output",
            str(output),
        ]
    )
    return code, output


def _shard_artifacts() -> dict[str, str]:
    return {
        f"shard-{i}/durations-shard-{i}.json": shards.record_text(files)
        for i, files in UPDATE_SHARDS.items()
    }


def test_updater_merges_five_shard_records(tmp_path, capsys):
    code, output = _run_updater(tmp_path, _shard_artifacts())
    assert code == 0
    merged = {k: v for files in UPDATE_SHARDS.values() for k, v in files.items()}
    assert output.read_text(encoding="utf-8") == shards.record_text(merged)
    out = capsys.readouterr().out
    assert "max/mean" in out
    assert "shard 5:" in out


@pytest.mark.parametrize(
    "mutate",
    ["drop_one", "add_sixth", "broken_json", "bad_value", "duplicate_key", "twice"],
)
def test_updater_rejects_a_bad_artifact_set(tmp_path, mutate):
    files = _shard_artifacts()
    if mutate == "drop_one":
        del files["shard-5/durations-shard-5.json"]
    elif mutate == "add_sixth":
        files["shard-6/durations-shard-6.json"] = shards.record_text({})
    elif mutate == "broken_json":
        files["shard-3/durations-shard-3.json"] = "{"
    elif mutate == "bad_value":
        files["shard-3/durations-shard-3.json"] = json.dumps(
            {"version": 1, "files": {"tests/unit/test_d.py": 4.5}}
        )
    elif mutate == "duplicate_key":
        files["shard-4/durations-shard-4.json"] = shards.record_text(
            {"tests/unit/test_a.py": 1}
        )
    else:
        files["again/durations-shard-2.json"] = files["shard-2/durations-shard-2.json"]
    code, output = _run_updater(tmp_path, files)
    assert code == 1
    assert not output.exists()


def _updater_args(tmp_path: Path, *extra: str) -> tuple[list[str], Path]:
    artifacts = tmp_path / "artifacts"
    for name, text in _shard_artifacts().items():
        target = artifacts / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    output = tmp_path / "out" / "shard_durations.json"
    return [str(artifacts), "--output", str(output), *extra], output


def test_updater_fails_when_collection_fails(tmp_path, capsys, monkeypatch):
    updater = _load_updater()
    monkeypatch.setattr(updater, "_collect_now", lambda: (2, UPDATE_COLLECTED))
    argv, output = _updater_args(tmp_path)
    assert updater.main(argv) == 1
    assert "FAIL: pytest --collect-only exited 2" in capsys.readouterr().out
    assert not output.exists()


def test_updater_fails_when_the_collected_file_is_absent(tmp_path, capsys):
    argv, output = _updater_args(tmp_path, "--collected", str(tmp_path / "no.txt"))
    assert _load_updater().main(argv) == 1
    assert "FAIL: collected list not found" in capsys.readouterr().out
    assert not output.exists()


# ── pytest 옵션 --shard-durations (#3036) ─────────────────────────────────


def _child_env() -> dict[str, str]:
    drop = ("COV_CORE_", "COVERAGE_", "PYTEST_XDIST_", "PYTEST_ADDOPTS")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def test_durations_option_writes_a_record_without_shard(tmp_path):
    target = tmp_path / "durations.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_shard_selection.py::test_parse_shard_accepts",
            "-p",
            "no:xdist",
            "-p",
            "no:cacheprovider",
            "-q",
            f"--shard-durations={target}",
        ],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == {"files", "version"}
    assert data["version"] == 1
    assert list(data["files"]) == ["tests/unit/test_shard_selection.py"]
    value = data["files"]["tests/unit/test_shard_selection.py"]
    assert isinstance(value, int) and value >= 0
    assert shards.load_record(target) == data["files"]
