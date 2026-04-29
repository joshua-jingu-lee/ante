"""Cold-path 용어 정합 회귀 가드 (#1139).

1.0 단일 active runtime 정책 하에서 cold-path 차단 기준은
"같은 ``config_dir``의 PID/socket guard"가 아니라 "active Ante runtime guard"다.

이 테스트는 cold-path 명령(`account create/delete/set-credentials`)을 다루는
SSOT 스펙에서 1.0 차단 기준 맥락에 옛 표현이 잔존하지 않는지 grep 단언한다.

대상 스펙:
- docs/specs/cli/03-commands.md
- docs/specs/account/09-cli.md
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SPEC_FILES = [
    REPO_ROOT / "docs" / "specs" / "cli" / "03-commands.md",
    REPO_ROOT / "docs" / "specs" / "account" / "09-cli.md",
]

# 1.0 차단 기준 맥락에서 등장해서는 안 되는 옛 표현 패턴.
# "같은" + (임의 텍스트) + "config_dir" + (임의 텍스트) + ("PID" 또는 "socket")
# 형태의 가드 설명을 잡는다.
LEGACY_GUARD_PATTERN = re.compile(
    r"같은[^\n]*config_dir[^\n]*(PID|socket)",
    re.IGNORECASE,
)


@pytest.mark.parametrize("spec_path", SPEC_FILES, ids=lambda p: p.name)
def test_cold_path_guard_terminology_uses_active_runtime(spec_path: Path) -> None:
    """cold-path 차단 기준은 active Ante runtime guard로 표현되어야 한다."""
    assert spec_path.exists(), f"spec 파일이 존재해야 함: {spec_path}"
    text = spec_path.read_text(encoding="utf-8")

    matches = LEGACY_GUARD_PATTERN.findall(text)
    assert not matches, (
        f"{spec_path} 에서 1.0 차단 기준 맥락의 옛 PID/socket guard 표현이 "
        f"잔존한다: {matches}. "
        f"#1139 정책: 'active Ante runtime guard'로 표현해야 한다."
    )
