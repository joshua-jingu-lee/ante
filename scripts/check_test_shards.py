"""단위 테스트 샤드의 분할과, 샤드 목록이 전체를 빠짐없이 나눴는지의 검사 (#2786).

``tests/conftest.py``가 ``--shard``의 해석과 분할에 이 모듈의 함수를 쓴다.
CI의 ``test`` 잡은 이 파일을 스크립트로 실행해 샤드들이 실행한 테스트의
목록을 ``pytest --collect-only -q``의 전체 목록과 견주고, 커버리지 자료 파일이
샤드마다 하나씩 있는지 센다. 하나라도 어긋나면 exit 1이다.

    python scripts/check_test_shards.py --shards 5 \\
        --collected collect-unit.txt --manifest-dir shard-artifacts
"""

from __future__ import annotations

import argparse
import re
import sys
import zlib
from pathlib import Path

MANIFEST_GLOB = "test-shard-*.txt"
COVERAGE_GLOB = "coverage-shard-*.data"
NODEID_LINE = re.compile(r"^tests/unit/.*::")
DIFF_LIMIT = 20


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
