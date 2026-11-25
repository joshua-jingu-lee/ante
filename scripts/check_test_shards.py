"""단위 테스트 샤드의 분할과, 샤드 목록이 전체를 빠짐없이 나눴는지의 검사 (#2786).

``tests/conftest.py``가 ``--shard``의 해석과 분할에 이 모듈의 함수를 쓴다.
분할은 ``tests/shard_durations.json``의 파일별 소요 시간(정수 센티초)으로
샤드의 부하를 고르게 맞춘다(#3036). 기록이 없거나 깨졌거나 수집된 파일과
겹치지 않으면 파일 경로의 crc32로 나눈다. 어느 쪽이든 파일 하나는 정확히
한 샤드에 든다.
CI의 ``test`` 잡은 이 파일을 스크립트로 실행해 샤드들이 실행한 테스트의
목록을 ``pytest --collect-only -q``의 전체 목록과 견주고, 커버리지 자료 파일이
샤드마다 하나씩 있는지 센다. 하나라도 어긋나면 exit 1이다.

    python scripts/check_test_shards.py --shards 5 \\
        --collected collect-unit.txt --manifest-dir shard-artifacts
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from pathlib import Path

MANIFEST_GLOB = "test-shard-*.txt"
COVERAGE_GLOB = "coverage-shard-*.data"
NODEID_LINE = re.compile(r"^tests/unit/.*::")
DIFF_LIMIT = 20
RECORD_PATH = Path(__file__).resolve().parents[1] / "tests" / "shard_durations.json"
RECORD_VERSION = 1


def parse_shard(value: str) -> tuple[int, int]:
    """``"<i>/<n>"``을 ``(i, n)``으로 푼다. ``1 <= i <= n``이 아니면 ValueError."""
    match = re.fullmatch(r"([0-9]+)/([0-9]+)", value)
    if match is None:
        raise ValueError(f"--shard must look like <i>/<n>, got {value!r}")
    index, total = int(match.group(1)), int(match.group(2))
    if total < 1 or not 1 <= index <= total:
        raise ValueError(f"--shard needs 1 <= i <= n, got {value!r}")
    return index, total


def shard_of(path: str, total: int) -> int:
    """테스트 파일 경로(rootdir 기준, POSIX 구분자)가 드는 샤드 번호(1부터)."""
    return zlib.crc32(path.encode("utf-8")) % total + 1


def _is_centiseconds(value: object) -> bool:
    return type(value) is int and value >= 0


def parse_record(text: str) -> dict[str, int] | None:
    """기록 JSON의 ``files``(경로 → 정수 센티초). 형식이 어긋나면 None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or set(data) != {"version", "files"}:
        return None
    version, files = data["version"], data["files"]
    if type(version) is not int or version != RECORD_VERSION:
        return None
    if not isinstance(files, dict):
        return None
    if not all(_is_centiseconds(value) for value in files.values()):
        return None
    return dict(files)


def load_record(path: str | Path) -> dict[str, int] | None:
    """기록 파일을 읽는다. 없거나 읽을 수 없거나 형식이 어긋나면 None."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse_record(text)


def record_text(files: dict[str, int]) -> str:
    """기록 파일의 내용. 키를 정렬하고 끝에 줄바꿈을 둔다."""
    payload = {"version": RECORD_VERSION, "files": dict(sorted(files.items()))}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def file_weights(
    file_counts: dict[str, int], record: dict[str, int] | None
) -> dict[str, int] | None:
    """파일별 무게(센티초). 기록에 없는 파일은 기록된 건당 시간으로 어림한다.

    기록이 없거나 수집된 파일과 하나도 겹치지 않으면 None이다.
    """
    if not record:
        return None
    known = sorted(path for path in file_counts if path in record)
    if not known:
        return None
    seconds = sum(record[path] for path in known)
    count = sum(file_counts[path] for path in known)
    if count == 0:
        return None
    return {
        path: record[path] if path in record else file_counts[path] * seconds // count
        for path in file_counts
    }


def assign_shards(
    file_counts: dict[str, int], record: dict[str, int] | None, total: int
) -> dict[str, int]:
    """파일 → 샤드 번호(1부터). 무거운 파일부터 가장 가벼운 샤드에 넣는다.

    무게를 낼 수 없으면 ``shard_of``로 나눈다. 결과는 입력의 순서와 무관하다.
    """
    weights = file_weights(file_counts, record)
    if weights is None:
        return {path: shard_of(path, total) for path in file_counts}
    loads = {index: 0 for index in range(1, total + 1)}
    assignment: dict[str, int] = {}
    for path in sorted(weights, key=lambda p: (-weights[p], p)):
        index = min(loads, key=lambda i: (loads[i], i))
        assignment[path] = index
        loads[index] += weights[path]
    return assignment


def resolve_manifest(value: str, base: str | Path) -> Path:
    """``--shard-manifest`` 값을 ``base``(pytest를 부른 디렉터리) 기준 절대 경로로."""
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path


def collected_nodeids(text: str) -> list[str]:
    """``--collect-only -q`` 출력에서 단위 테스트 nodeid 줄만 정렬해 돌려준다."""
    return sorted(line for line in text.splitlines() if NODEID_LINE.match(line))


def check(
    collected: list[str],
    manifests: dict[str, list[str]],
    shards: int,
    coverage_files: int,
) -> list[str]:
    """어긋남을 사람이 읽을 줄로 돌려준다. 빈 목록이면 통과다."""
    if shards < 1:
        return [f"shard count must be >= 1, got {shards}"]
    if not collected:
        return ["collected list is empty"]
    errors: list[str] = []
    if len(manifests) != shards:
        errors.append(
            f"expected {shards} shard lists, found {len(manifests)}: "
            f"{sorted(manifests)}"
        )
    if coverage_files != shards:
        errors.append(
            f"expected {shards} coverage files, found {coverage_files} "
            f"({COVERAGE_GLOB})"
        )
    seen: dict[str, int] = {}
    for ids in manifests.values():
        for nodeid in ids:
            seen[nodeid] = seen.get(nodeid, 0) + 1
    duplicates = sorted(nodeid for nodeid, count in seen.items() if count > 1)
    if duplicates:
        errors.append(f"{len(duplicates)} test(s) ran in more than one shard:")
        errors.extend(f"  {nodeid}" for nodeid in duplicates[:DIFF_LIMIT])
    expected = set(collected)
    missing = sorted(expected - seen.keys())
    extra = sorted(seen.keys() - expected)
    if missing:
        errors.append(f"{len(missing)} collected test(s) ran in no shard:")
        errors.extend(f"  - {nodeid}" for nodeid in missing[:DIFF_LIMIT])
    if extra:
        errors.append(f"{len(extra)} shard test(s) are not in the collected list:")
        errors.extend(f"  + {nodeid}" for nodeid in extra[:DIFF_LIMIT])
    return errors


def _read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shards", required=True, help="number of shards")
    parser.add_argument(
        "--collected", required=True, type=Path, help="--collect-only -q output"
    )
    parser.add_argument(
        "--manifest-dir", required=True, type=Path, help=f"dir with {MANIFEST_GLOB}"
    )
    args = parser.parse_args(argv)
    if re.fullmatch(r"[0-9]+", args.shards) is None:
        print(f"FAIL: shard count is not an integer: {args.shards!r}")
        return 1
    shards = int(args.shards)
    if not args.collected.is_file():
        print(f"FAIL: collected list not found: {args.collected}")
        return 1
    collected = collected_nodeids(args.collected.read_text(encoding="utf-8"))
    manifests = {
        path.name: _read_lines(path)
        for path in sorted(args.manifest_dir.glob(MANIFEST_GLOB))
    }
    coverage_files = len(list(args.manifest_dir.glob(COVERAGE_GLOB)))
    errors = check(collected, manifests, shards, coverage_files)
    if errors:
        print("FAIL: shard lists do not partition the unit tests")
        print("\n".join(errors))
        return 1
    total = sum(len(ids) for ids in manifests.values())
    print(
        f"OK: {shards} shards ran {total} tests == {len(collected)} collected, "
        f"no duplicates, {coverage_files} coverage files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
