"""샤드 잡의 소요 시간 기록을 합쳐 ``tests/shard_durations.json``을 쓴다 (#3036).

CI의 ``test-shard`` 잡은 ``--shard-durations``로 ``durations-shard-<i>.json``을
산출물 ``shard-<i>``에 싣는다. 그 산출물을 받은 디렉터리를 넘기면 샤드마다
정확히 한 파일이 있는지 확인하고, 합친 기록을 쓴 뒤 그 기록과 현재 수집
건수로 예측한 샤드별 부하와 ``max/mean``을 출력한다. 어긋나면 exit 1이다.

    gh run download <run> -p 'shard-*' -D <dir>
    python scripts/update_test_shard_durations.py <dir>
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
DURATIONS_GLOB = "durations-shard-*.json"
DURATIONS_NAME = re.compile(r"durations-shard-([0-9]+)\.json")
DEFAULT_SHARDS = 5


def _load_shards() -> ModuleType:
    path = REPO_ROOT / "scripts" / "check_test_shards.py"
    spec = importlib.util.spec_from_file_location("_ante_check_test_shards", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shard tools: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shards = _load_shards()


def merge_records(
    directory: Path, total: int
) -> tuple[dict[str, int] | None, list[str]]:
    """``directory`` 아래 샤드 기록을 합친다. 어긋나면 ``(None, 오류 줄)``."""
    found: dict[int, list[Path]] = {}
    errors: list[str] = []
    for path in sorted(directory.rglob(DURATIONS_GLOB)):
        match = DURATIONS_NAME.fullmatch(path.name)
        if match is None:
            errors.append(f"unexpected file name: {path}")
            continue
        found.setdefault(int(match.group(1)), []).append(path)
    expected = set(range(1, total + 1))
    if set(found) != expected:
        errors.append(
            f"expected durations for shards {sorted(expected)}, found {sorted(found)}"
        )
    errors.extend(
        f"shard {index} has {len(paths)} duration files"
        for index, paths in sorted(found.items())
        if len(paths) != 1
    )
    if errors:
        return None, errors
    merged: dict[str, int] = {}
    for index in sorted(found):
        path = found[index][0]
        record = shards.load_record(path)
        if record is None:
            errors.append(f"invalid duration record: {path}")
            continue
        for name, value in record.items():
            if name in merged:
                errors.append(f"{name} appears in more than one shard")
            merged[name] = value
    return (None, errors) if errors else (merged, [])


def collected_counts(text: str) -> dict[str, int]:
    """``--collect-only -q`` 출력에서 파일별 수집 건수."""
    counts: dict[str, int] = {}
    for nodeid in shards.collected_nodeids(text):
        path = nodeid.split("::", 1)[0]
        counts[path] = counts.get(path, 0) + 1
    return counts


def _collect_now() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/", "--collect-only", "-q"]
        + ["-p", "no:xdist"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def predicted_loads(
    counts: dict[str, int], record: dict[str, int], total: int
) -> list[int]:
    """기록과 수집 건수로 예측한 샤드별 부하(센티초)."""
    weights = shards.file_weights(counts, record) or {}
    loads = [0] * total
    for path, index in shards.assign_shards(counts, record, total).items():
        loads[index - 1] += weights.get(path, 0)
    return loads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path, help="downloaded shard artifacts")
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    parser.add_argument("--output", type=Path, default=shards.RECORD_PATH)
    parser.add_argument(
        "--collected", type=Path, help="--collect-only -q output (default: collect)"
    )
    args = parser.parse_args(argv)
    if args.shards < 1:
        print(f"FAIL: shard count must be >= 1, got {args.shards}")
        return 1
    if not args.directory.is_dir():
        print(f"FAIL: artifact directory not found: {args.directory}")
        return 1
    merged, errors = merge_records(args.directory, args.shards)
    if merged is None:
        print("FAIL: shard duration records do not merge")
        print("\n".join(errors))
        return 1
    if args.collected is not None:
        text = args.collected.read_text(encoding="utf-8")
    else:
        text = _collect_now()
    counts = collected_counts(text)
    if not counts:
        print("FAIL: collected list is empty")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(shards.record_text(merged), encoding="utf-8")
    loads = predicted_loads(counts, merged, args.shards)
    mean = sum(loads) / args.shards
    for index, load in enumerate(loads, start=1):
        print(f"shard {index}: {load / 100:.1f}s")
    ratio = max(loads) / mean if mean else 0.0
    print(
        f"wrote {len(merged)} files to {args.output}; "
        f"new files {len(set(counts) - set(merged))}; max/mean {ratio:.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
