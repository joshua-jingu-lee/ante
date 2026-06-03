"""Data CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 6).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
data 도메인 6 leaf 의 ``OutputContract`` 와 ``ante data ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / sub-PR 2 (bot) / sub-PR 3
(approval) / sub-PR 4 (treasury) / sub-PR 5 (strategy) 1:1 동형 패턴.
drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``data.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제 callsite
shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면 본 test 가
즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

10 시나리오 (6 leaf + registry sanity +1 + list empty 분기 +1 + list
non-empty +1 + validate empty 분기 +1):

0. registry sanity — data 6 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``list`` empty → ``raw_legacy`` (``{datasets: [], count: 0}``)
2. ``list`` non-empty → ``raw_legacy`` (``{datasets: [...], count: N}``)
3. ``info`` (found) → ``raw_legacy`` (``fmt.output({dataset, preview})``)
4. ``delete`` (success) → ``raw_legacy`` (JSON 모드 ``fmt.output(result)``)
5. ``schema`` → ``raw_legacy`` (``fmt.output({column: dtype_str})``)
6. ``storage`` → ``raw_legacy`` (``fmt.output(summary, "Total: ...")``)
7. ``validate`` empty (no symbols) → ``raw_legacy`` (``{message, results: []}``)
8. ``validate`` non-empty → ``raw_legacy`` (``{results, summary}``)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# ── envelope shape predicates (envelopes.md SSOT, 동형 정책) ───────────────

_STANDARD_KEYS = frozenset({"status", "message", "data"})


def _is_standard_envelope(payload: Any) -> bool:
    """``{status: "ok", message, data}`` 3 필수 키가 모두 존재하는지."""
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and set(payload.keys()) >= _STANDARD_KEYS
        and isinstance(payload.get("message"), str)
        and isinstance(payload.get("data"), (dict, type(None)))
    )


def _is_raw_legacy_payload(payload: Any) -> bool:
    """평면 dict / list 로 standard envelope 의 3 필수 키 셋이 부재함을 단언.

    raw_legacy 는 ``fmt.output(dict)`` / ``fmt.table(rows)`` 출력의 super-set
    이다. ``status``/``message``/``data`` 3 키가 동시에 갖춰지고 ``status ==
    "ok"`` 면 standard envelope 으로 분류 (애매한 경계 방지). 그렇지 않으면
    모든 평면 도메인 payload 는 raw_legacy.
    """
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    if (
        set(payload.keys()) >= _STANDARD_KEYS
        and payload.get("status") == "ok"
        and isinstance(payload.get("data"), dict)
    ):
        return False
    return True


# ── registry entry 정합 sanity (envelope vocab) ───────────────────────────


def test_registry_data_entries_envelopes_classified() -> None:
    """data 6 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 6 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    data_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("data",)
    ]
    assert len(data_entries) == 6, (
        f"data 6 entries 가 모두 등록되어야 한다. 실제: {len(data_entries)}"
    )
    for path, contract in data_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot/approval/treasury/strategy 동형) ───────


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


@pytest.fixture(autouse=True)
def bypass_auth():
    """master member 로 인증 우회 (동형 패턴)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json data ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (treasury /
    strategy drift test 동형).
    """
    text = output.lstrip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    start_brace = text.find("{")
    start_bracket = text.find("[")
    candidates = [s for s in (start_brace, start_bracket) if s >= 0]
    assert candidates, f"JSON 시작 토큰을 찾을 수 없다: {output!r}"
    start = min(candidates)
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return obj


# ── 1. list empty → raw_legacy ─────────────────────────────────────────────


def test_data_list_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data list`` empty: ``{datasets: [], count: 0}`` 평면 (raw_legacy).

    data.py:75: ``fmt.output({"datasets": [], "count": 0})`` 분기. text/JSON
    양쪽 모두 동일 평면 dict 를 echo (`fmt.output` 내부 branch). JSON 모드를
    정확히 단언한다.
    """
    with patch(
        "ante.data.datasets.list_datasets",
        return_value={"items": [], "total": 0},
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "list",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"datasets": [], "count": 0}


# ── 1b. list out-of-range page (total>0, items empty) → count==total (#1986) ─


def test_data_list_out_of_range_page_count_preserves_total(tmp_path) -> None:
    """``data list`` out-of-range offset: items 빈 페이지여도 count==total (#1986).

    ``list_datasets`` 는 빈 items 에도 ``total`` (전체 매칭 수) 를 반환한다.
    큰 ``--offset`` 으로 페이지가 비어도 ``count`` 는 전체 매칭 수
    (``result["total"]``) 를 유지해야 한다 (이전엔 ``0`` 하드코딩 → 회귀).
    """
    with patch(
        "ante.data.datasets.list_datasets",
        return_value={"items": [], "total": 3129},
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "list",
                "--data-path",
                str(tmp_path),
                "--offset",
                "100000",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data list out-of-range: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"datasets": [], "count": 3129}


# ── 2. list non-empty → raw_legacy ─────────────────────────────────────────


def test_data_list_non_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data list`` non-empty: ``{datasets: [...], count: N}`` 평면.

    ``fmt.output({"datasets": datasets, "count": result["total"]})`` JSON 분기.
    ``_enrich`` 후 InstrumentService 가 name 을 추가하지만 본 fixture 는
    InstrumentService 까지 mock 하기 어려우므로 ``load_readonly`` (read-only
    캐시 워밍 — #1984) 와 ``get_name`` 을 patch 한다.
    """
    items = [
        {
            "id": "005930__1d",
            "symbol": "005930",
            "timeframe": "1d",
            "data_type": "ohlcv",
            "start_date": "2024-01-02",
            "end_date": "2026-01-15",
            "row_count": 0,
            "file_size": 0,
        }
    ]
    with (
        patch(
            "ante.data.datasets.list_datasets",
            return_value={"items": items, "total": 1},
        ),
        patch(
            "ante.instrument.service.InstrumentService.load_readonly",
            new=AsyncMock(),
        ),
        patch(
            "ante.instrument.service.InstrumentService.get_name",
            return_value="삼성전자",
        ),
        patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(),
        ),
        patch(
            "ante.core.database.Database.close",
            new=AsyncMock(),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "list",
                "--data-path",
                str(tmp_path),
                "--db-path",
                str(tmp_path / "ante.db"),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data list non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload["count"] == 1
    assert isinstance(payload["datasets"], list)
    assert payload["datasets"][0]["id"] == "005930__1d"
    assert payload["datasets"][0]["name"] == "삼성전자"


# ── 3. info (found) → raw_legacy ───────────────────────────────────────────


def test_data_info_found_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data info`` 발견: ``fmt.output(result)`` 평면 ``{dataset, preview}``.

    data.py:135: ``if fmt.is_json: fmt.output(result)`` → ``{dataset: {id,
    symbol, timeframe, data_type, start_date, end_date, row_count, file_size},
    preview: [...]}``.
    """
    detail = {
        "dataset": {
            "id": "005930__1d",
            "symbol": "005930",
            "timeframe": "1d",
            "data_type": "ohlcv",
            "start_date": "2024-01-02",
            "end_date": "2026-01-15",
            "row_count": 500,
            "file_size": 12_345,
        },
        "preview": [
            {"date": "2024-01-02", "open": 70000, "close": 71000},
        ],
    }
    with patch(
        "ante.data.datasets.get_dataset_detail",
        return_value=detail,
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "info",
                "005930__1d",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data info found: standard envelope 아님. payload={payload!r}"
    )
    assert payload["dataset"]["id"] == "005930__1d"
    assert payload["preview"][0]["open"] == 70000


# ── 4. delete (success) → raw_legacy (JSON 분기) ───────────────────────────


def test_data_delete_success_json_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data delete`` 성공: JSON 모드 ``fmt.output(result)`` 평면 dict.

    data.py:207-208: ``if fmt.is_json: fmt.output(result)`` → ``{dataset_id,
    symbol, timeframe, data_type, path, deleted}`` 평면. text 모드는
    ``fmt.success(f"데이터셋 삭제 완료: ...", result)`` 이지만 JSON 모드는
    raw_legacy (account ``set-credentials`` / bot ``signal-key`` / treasury
    ``set-balance`` 동형 정책).
    """
    deletion_result = {
        "dataset_id": "005930__1d",
        "symbol": "005930",
        "timeframe": "1d",
        "data_type": "ohlcv",
        "path": str(tmp_path / "ohlcv" / "1d" / "005930"),
        "deleted": True,
    }
    with patch(
        "ante.data.datasets.delete_dataset",
        return_value=deletion_result,
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "delete",
                "005930__1d",
                "--yes",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data delete success JSON: standard envelope 아님. payload={payload!r}"
    )
    assert payload["dataset_id"] == "005930__1d"
    assert payload["deleted"] is True


# ── 5. schema → raw_legacy ─────────────────────────────────────────────────


def test_data_schema_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data schema``: ``fmt.output({k: str(v) ...})`` 평면 dict.

    data.py:223: ``fmt.output({k: str(v) for k, v in OHLCV_SCHEMA.items()})``.
    OHLCV_SCHEMA 평면 dict (column → dtype_str).
    """
    result = _invoke(
        [
            "--format",
            "json",
            "data",
            "schema",
            "--data-path",
            str(tmp_path),
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data schema: standard envelope 아님. payload={payload!r}"
    )
    # OHLCV_SCHEMA 의 정규 column 들이 포함되는지 sanity check
    # (data/schemas.py SSOT — timestamp/symbol/open/high/low/close/volume/...).
    assert "timestamp" in payload
    assert "open" in payload
    assert "close" in payload
    assert "volume" in payload


# ── 6. storage → raw_legacy ────────────────────────────────────────────────


def test_data_storage_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data storage``: ``fmt.output(summary, "Total: ...")`` 평면 dict.

    data.py:247-250: ``fmt.output({total_bytes, total_mb, by_timeframe},
    "Total: {total_mb} MB")``. JSON 모드는 template ignore 하고 평면 dict
    그대로 dump (formatter.py:54-55).
    """
    with patch(
        "ante.data.store.ParquetStore.get_storage_usage",
        return_value={"1d": 1_048_576, "1m": 524_288},
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "storage",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data storage: standard envelope 아님. payload={payload!r}"
    )
    assert "total_bytes" in payload
    assert "total_mb" in payload
    assert "by_timeframe" in payload
    assert payload["total_bytes"] == 1_048_576 + 524_288


# ── 7. validate empty (no symbols) → raw_legacy ───────────────────────────


def test_data_validate_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data validate`` empty: ``{message, results: []}`` 평면.

    data.py:313: ``fmt.output({"message": "검증할 데이터가 없습니다.",
    "results": []})`` 분기. ``list_symbols`` 가 빈 리스트를 반환할 때.
    """
    with patch(
        "ante.data.store.ParquetStore.list_symbols",
        return_value=[],
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "validate",
                "--timeframe",
                "1d",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data validate empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "검증할 데이터가 없습니다.", "results": []}


# ── 8. validate non-empty → raw_legacy ────────────────────────────────────


def test_data_validate_non_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``data validate`` non-empty: ``{results, summary}`` 평면.

    data.py:326: ``if fmt.is_json: fmt.output({"results": [...], "summary":
    {total_files, valid, corrupted, fixed}})``. ``ParquetStore.validate`` 가
    per-symbol 결과 dict 를 반환.
    """
    validate_result = {
        "symbol": "005930",
        "timeframe": "1d",
        "total": 3,
        "valid": 3,
        "corrupted": 0,
        "corrupted_files": [],
    }
    with (
        patch(
            "ante.data.store.ParquetStore.list_symbols",
            return_value=["005930"],
        ),
        patch(
            "ante.data.store.ParquetStore.validate",
            return_value=validate_result,
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "data",
                "validate",
                "--timeframe",
                "1d",
                "--data-path",
                str(tmp_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"data validate non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert "results" in payload
    assert "summary" in payload
    assert payload["summary"]["total_files"] == 3
    assert payload["summary"]["valid"] == 3
    assert payload["summary"]["corrupted"] == 0
    assert payload["summary"]["fixed"] is False


# ── 9. data list fundamental+timeframe 모순 조합 거부 (#1983) ────────────────
#
# fundamental 데이터셋은 timeframe="" 으로 저장되며 timeframe 차원이 없다.
# `--timeframe` 은 OHLCV bar 전용 필터이므로 `--type fundamental --timeframe
# <tf>` 조합은 조용히 무시(전체 fundamental 반환)되어선 안 되고
# `validate_dataset_filters` 단계에서 ValueError → CLI `DATA_INVALID_FILTER`
# exit 1 로 거부되어야 한다.
#
# precedence: ① timeframe vocabulary (기존) → ② data_type 유효성 (기존)
#             → ③ fundamental+timeframe 모순 거부 (#1983 신규).


class TestValidateDatasetFiltersFundamentalTimeframe:
    """``validate_dataset_filters`` fundamental+timeframe 모순 거부 단위 (#1983)."""

    def test_fundamental_with_timeframe_rejected(self) -> None:
        """(a) 재현: fundamental + 유효 timeframe → ValueError 거부."""
        from ante.data.datasets import validate_dataset_filters

        with pytest.raises(ValueError) as exc_info:
            validate_dataset_filters(data_type="fundamental", timeframe="1d")
        # 모순 거부 메시지 (vocabulary 메시지가 아님 — precedence 통과 후).
        assert "fundamental" in str(exc_info.value)
        assert "timeframe" in str(exc_info.value)
        assert "허용되지 않은 timeframe" not in str(exc_info.value)

    def test_fundamental_without_timeframe_returns_fundamental(self) -> None:
        """(b) 회귀: fundamental + timeframe 미지정 → "fundamental" 정상 반환."""
        from ante.data.datasets import validate_dataset_filters

        assert (
            validate_dataset_filters(data_type="fundamental", timeframe=None)
            == "fundamental"
        )

    def test_ohlcv_with_timeframe_returns_ohlcv(self) -> None:
        """(c) 회귀: ohlcv + 유효 timeframe → "ohlcv" 정상 반환 (거부 안 함)."""
        from ante.data.datasets import validate_dataset_filters

        assert validate_dataset_filters(data_type="ohlcv", timeframe="1d") == "ohlcv"

    def test_fundamental_with_invalid_timeframe_hits_vocabulary_first(self) -> None:
        """(d) 회귀: fundamental + 비-canonical timeframe → vocabulary error 우선.

        precedence ① (timeframe vocabulary) 가 ③ (모순 거부) 보다 먼저 평가되어,
        invalid timeframe 메시지("허용되지 않은 timeframe")가 반환되어야 한다.
        """
        from ante.data.datasets import validate_dataset_filters

        with pytest.raises(ValueError) as exc_info:
            validate_dataset_filters(data_type="fundamental", timeframe="invalid")
        assert "허용되지 않은 timeframe" in str(exc_info.value)

    def test_timeframe_only_without_data_type_returns_none(self) -> None:
        """(e) 회귀: data_type 미지정 + timeframe → None 반환 (비목표, 기존 동작).

        data_type=None + timeframe 조합은 별개 contract (Non-Goal) 이므로
        기존대로 None 을 반환하며 모순 거부 대상이 아니다.
        """
        from ante.data.datasets import validate_dataset_filters

        assert validate_dataset_filters(timeframe="1d") is None


def test_data_list_fundamental_with_timeframe_rejected_cli(tmp_path) -> None:
    """CLI: ``data list --type fundamental --timeframe 1d`` → exit 1 +
    ``DATA_INVALID_FILTER`` (#1983).

    CLI 경계의 ``except ValueError → fmt.error(code="DATA_INVALID_FILTER");
    raise SystemExit(1)`` 매핑을 통해 모순 조합이 거부되는지 락한다.
    조용히 전체 fundamental 을 반환(exit 0)하던 회귀 증상을 차단한다.
    """
    result = _invoke(
        [
            "--format",
            "json",
            "data",
            "list",
            "--type",
            "fundamental",
            "--timeframe",
            "1d",
            "--data-path",
            str(tmp_path),
        ]
    )
    assert result.exit_code == 1, result.output

    payload = _load_json_payload(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "DATA_INVALID_FILTER"
