"""속성 테스트의 hypothesis 프로필.

- ``ci``(기본): 결정적이고 예를 저장하지 않는다. CI와 로컬의 일반 실행이
  같은 예를 돈다.
- ``dev``: ``ANTE_HYPOTHESIS_PROFILE=dev``로 고른다. 무작위이고 예를 더 많이 돌며
  찾은 반례를 ``.hypothesis/``에 저장한다. 반례를 찾을 때 쓴다.

``deadline``을 끄는 이유: 한 걸음이 aiosqlite 쓰기라 시간이 흔들린다.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    max_examples=50,
    stateful_step_count=25,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    deadline=None,
    print_blob=True,
    max_examples=500,
    stateful_step_count=40,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("ANTE_HYPOTHESIS_PROFILE", "ci"))
