"""Backtest Service — 메인 프로세스에서 백테스트를 관리."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import re
import sys
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.exceptions import BacktestConfigError, BacktestError
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult
from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical
from ante.core.market_data_vocab import (
    CANONICAL_TIMEFRAMES,
    is_krx_symbol,
    is_valid_timeframe,
)
from ante.data.store import ParquetStore
from ante.strategy.loader import StrategyLoader
from ante.strategy.validator import StrategyValidator

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

BACKTEST_RESULT_SENTINEL = "__ANTE_BACKTEST_RESULT__"

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class BacktestService:
    """백테스트 실행 관리.

    in-process 실행과 subprocess 격리 실행 두 모드를 지원한다.
    """

    def __init__(
        self,
        data_path: str = "data/",
        eventbus: EventBus | None = None,
    ) -> None:
        self._data_path = data_path
        self._eventbus = eventbus
        self._running: dict[str, asyncio.Task] = {}

    async def run(
        self,
        config: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> BacktestResult:
        """백테스트를 in-process로 실행."""
        from pathlib import Path

        validated = self._validate_config(config)

        # #2039: StrategyLoader.load(import)가 전략 파일을 실행하기 전에
        #        StrategyValidator로 정적(AST) 안전성 검증을 수행한다.
        #        validate 자체는 ast.parse 기반이라 전략 코드를 실행하지
        #        않으므로, 금지 모듈/builtin/top-level 코드가 import 시점에
        #        실행되는 것을 차단한다. backtest run은 public CLI에서 파일
        #        경로를 직접 받아 in-process/subprocess 양쪽 모두 이
        #        service.run 을 거치므로, load 직전 검증으로 모든 경로에서
        #        우회를 막는다. valid=False면 load를 호출하지 않고 즉시
        #        raise 하여 금지 코드가 실행되지 않는다(warnings는 비차단).
        strategy_path = Path(validated.strategy_path)
        val_result = StrategyValidator().validate(strategy_path)
        if not val_result.valid:
            msg = f"전략 검증 실패: {'; '.join(val_result.errors)}"
            raise BacktestConfigError(msg)

        strategy_cls = StrategyLoader.load(strategy_path)

        # #2060: CLI ``--symbols``/``--timeframe`` 생략 시 ``StrategyMeta``
        # 로 fallback 한다. ``_validate_config`` 는 load 전이라 meta 를 모르므로
        # 여기(load 후)에서 effective 값을 resolve·재검증한다.
        #   - symbols: 명시(validated.symbols) 우선, 비면 meta.symbols
        #   - timeframe: 명시(config["timeframe"] 비-None) 우선, 생략(None)이면
        #     meta.timeframe (None 은 _validate_config 가 early 검증을 deferred
        #     했으므로 여기서 effective 값으로 재검증)
        # meta 가 invalid timeframe/symbol 을 선언했어도 effective 재검증으로
        # 차단한다(전략 meta 도 vocab SSOT 를 우회 못함).
        meta = strategy_cls.meta
        eff_symbols = validated.symbols or list(meta.symbols or [])
        cfg_timeframe = config.get("timeframe", "1d")
        eff_timeframe = cfg_timeframe if cfg_timeframe is not None else meta.timeframe

        # effective 값 vocab 재검증 (early 검증과 동일 helper 공유). meta
        # 선언 invalid 도 BacktestConfigError 로 차단. exchange 는 validated
        # (이미 canonical 검증 통과) 기준으로 KRX-shape 적용.
        self._validate_timeframe_vocab(eff_timeframe)
        self._validate_symbols_vocab(eff_symbols, validated.exchange)

        # downstream(provider/executor/data load/result.config)에는 None 이
        # 새지 않는 effective ``BacktestConfig`` 만 흘린다(Codex 제약). validated
        # 를 effective symbols/timeframe 으로 치환한 사본을 구성한다.
        effective = replace(
            validated,
            symbols=eff_symbols,
            timeframe=eff_timeframe,
        )

        if not effective.symbols:
            # CLI+meta 모두 symbols 없음 → executor universe 빈 상태로 0-step
            # 성공이 silent 하게 끝나던 사유(#2060)를 명시 기록한다.
            logger.warning(
                "백테스트 대상 종목이 없습니다(CLI --symbols 생략 + "
                "StrategyMeta.symbols 미설정 '%s'): 데이터셋 0개·0-step 으로 "
                "종료될 수 있습니다.",
                meta.name,
            )

        store = ParquetStore(
            base_path=effective.data_paths[0],
        )
        data_provider = BacktestDataProvider(
            store=store,
            start_date=effective.start_date,
            end_date=effective.end_date,
            exchange=effective.exchange,
            # run timeframe을 provider에 인지시켜, 내부 read 경로
            # (체결가/equity/지표)가 ``{symbol}:{timeframe}`` 캐시 키를
            # 조회하도록 한다(#2012). 미전달 시 1d로 떨어져 비-1d run의
            # 체결가가 1d 종가로 새는 버그가 생긴다.
            timeframe=effective.timeframe,
        )

        for symbol in effective.symbols:
            data_provider.load(symbol, effective.timeframe)

        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=data_provider,
            initial_balance=effective.initial_balance,
            buy_commission_rate=effective.buy_commission_rate,
            sell_commission_rate=effective.sell_commission_rate,
            slippage_rate=effective.slippage_rate,
            exchange=effective.exchange,
            # config.symbols universe를 executor에 전달해, 전략이 universe 밖
            # Signal.symbol을 반환해도 거래(체결)하지 않게 한다(#2072). 빈
            # symbols(universe 미설정)는 frozenset()이 되어 거부하지 않는다.
            symbols=effective.symbols,
        )

        result = await executor.run(progress_callback=progress_callback)
        result.config = effective
        result.datasets = data_provider.loaded_datasets

        # #1998: 결과를 durable artifact(JSON)로 저장하고 경로를 result 에 기록한다.
        # 이 경로가 BacktestCompleteEvent.result_path / backtest_runs.result_path
        # 로 전파되어 ReportDraftGenerator 가 자동 리포트 초안을 생성한다. 저장
        # 디렉토리는 effective.data_paths[0] (항상 채워짐) 하위 ``.backtest/results``
        # 를 anchor 로 쓴다. BacktestResult 에 wall-clock timestamp 필드가 없어
        # UUID 로 충돌 없이 네이밍한다.
        result.result_path = self._save_result_artifact(result, effective)

        # BacktestCompleteEvent 발행
        await self._publish_complete_event(result)

        return result

    def _save_result_artifact(
        self,
        result: BacktestResult,
        effective: BacktestConfig,
    ) -> str:
        """결과를 durable JSON artifact 로 저장하고 경로를 반환한다 (#1998).

        저장 실패(read-only/ephemeral data dir 등)는 backtest 자체를 실패시키지
        않는다 — warning 을 남기고 ``""`` 를 반환하여 빈 result_path 로 이벤트가
        발행되게 한다(기존 무회귀 동작 보존, 자동 draft 만 skip). ``to_dict()``
        의 직렬화 계약 그대로 저장하므로 ReportDraftGenerator._load_result 가
        그대로 소비한다.
        """
        from pathlib import Path

        try:
            artifact_dir = Path(effective.data_paths[0]) / ".backtest" / "results"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            name = (
                f"{result.strategy_name}_v{result.strategy_version}_"
                f"{uuid.uuid4().hex}.json"
            )
            path = artifact_dir / name
            path.write_text(json.dumps(result.to_dict(), default=str))
        except OSError as e:
            logger.warning(
                "백테스트 결과 artifact 저장 실패(자동 리포트 초안 skip): %s",
                e,
            )
            return ""
        else:
            logger.info("백테스트 결과 artifact 저장: %s", path)
            return str(path)

    async def run_subprocess(self, config: dict[str, Any]) -> dict:
        """백테스트를 subprocess로 격리 실행 (D-004).

        ``ante backtest run`` CLI 의 격리 실행 경로다(#2001). ``python -m
        ante.backtest.runner`` 자식 프로세스를 띄워 stdin 으로 JSON config 를
        전달하고, stdout 의 ``BACKTEST_RESULT_SENTINEL`` 라인만 파싱한 dict 를
        반환한다. returncode≠0 또는 sentinel 라인 부재는 ``BacktestError`` 다.

        반환 dict 는 ``runner.run_backtest`` 가 emit 하는 additive envelope 로,
        ``to_dict()`` 키 superset 에 더해 런타임 메타데이터 ``result_path`` /
        ``strategy_name`` / ``strategy_version`` 를 포함한다. 자식 프로세스의
        ``run()`` 이 durable artifact 를 저장하고 그 경로를 ``result_path`` 로
        surface 하므로, CLI ``_save_backtest_run`` 이 이를
        ``backtest_runs.result_path`` 로 영속해 추적성을 전파한다(#1998).

        이 경로는 부모 프로세스에서 ``BacktestCompleteEvent`` 를 발행하지 않는다
        (격리된 자식 프로세스에는 eventbus 가 없다). ``to_dict()`` 직렬화 계약은
        무변경이며, 런타임 3키는 envelope 반환에서만 보강된다.
        """
        self._validate_config(config)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "ante.backtest.runner",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(
            input=json.dumps(config).encode(),
        )

        if proc.returncode != 0:
            msg = f"Backtest subprocess failed: {stderr.decode()}"
            raise BacktestError(msg)

        stdout_text = stdout.decode()
        for line in stdout_text.splitlines():
            if line.startswith(BACKTEST_RESULT_SENTINEL):
                payload = line[len(BACKTEST_RESULT_SENTINEL) :]
                return json.loads(payload)
        msg = "Backtest subprocess did not emit a result line"
        raise BacktestError(msg)

    async def _publish_complete_event(
        self,
        result: BacktestResult,
    ) -> None:
        """BacktestCompleteEvent 발행."""
        if not self._eventbus:
            return

        from ante.eventbus.events import BacktestCompleteEvent

        strategy_id = f"{result.strategy_name}_v{result.strategy_version}"
        event = BacktestCompleteEvent(
            backtest_id=strategy_id,
            strategy_id=strategy_id,
            status="completed",
            # #1998: run() 이 저장한 durable artifact 경로(저장 실패 시 ""). 빈
            # 경로면 ReportDraftGenerator 가 자동 초안을 skip 한다(무회귀).
            result_path=result.result_path,
        )
        await self._eventbus.publish(event)
        logger.info("BacktestCompleteEvent 발행: %s", strategy_id)

    def _validate_timeframe_vocab(self, timeframe: object) -> None:
        """timeframe vocabulary 검증 (#1604). invalid → BacktestConfigError.

        early(_validate_config)와 effective(run, #2060) 양쪽이 공유하는 단일
        helper. ``str()`` 캐스팅 없이 non-str 도 ``is_valid_timeframe`` 의
        non-str→False 가드를 통해 거부한다.
        """
        if not isinstance(timeframe, str) or not is_valid_timeframe(timeframe):
            msg = (
                f"Invalid timeframe: {timeframe!r}. "
                f"Allowed: {', '.join(CANONICAL_TIMEFRAMES)}"
            )
            raise BacktestConfigError(msg)

    def _validate_symbols_vocab(
        self,
        symbols: object,
        exchange: str,
        *,
        raw: object | None = None,
    ) -> None:
        """symbols 구조/빈/KRX-shape 검증 (#1604/#2060 공유 helper).

        early(_validate_config)와 effective(run, meta fallback) 양쪽이 동일
        로직을 쓰도록 추출. ``raw`` 는 에러 메시지에 노출할 원본 입력값(없으면
        ``symbols`` 자체). ``exchange == "KRX"`` 일 때만 6자리 shape 검증.
        SSOT(`is_krx_symbol`)의 non-str→False 가드 보존 — ``str()`` 캐스팅 금지.
        """
        shown = symbols if raw is None else raw
        if not isinstance(symbols, list) or not all(
            isinstance(s, str) for s in symbols
        ):
            msg = f"Invalid symbols (expected list[str]): {shown!r}"
            raise BacktestConfigError(msg)
        if any(not s.strip() for s in symbols):
            msg = f"Invalid symbols (empty/blank segment): {shown!r}"
            raise BacktestConfigError(msg)
        if exchange == "KRX":
            # resolved exchange == KRX 신규 입력 한정 (core.md
            # ``### KRX symbol shape``). 비-KRX exchange의 symbol shape은
            # 미검증 (NYSE+AAPL 비거부).
            for s in symbols:
                if not is_krx_symbol(s):
                    msg = (
                        f"Invalid KRX symbol: {s!r}. "
                        "Expected 6-digit canonical KRX symbol shape."
                    )
                    raise BacktestConfigError(msg)

    def _validate_config(self, config: dict[str, Any]) -> BacktestConfig:
        """설정 검증 후 BacktestConfig를 반환."""
        required = ["strategy_path", "start_date", "end_date"]
        missing = [k for k in required if k not in config]
        if missing:
            msg = f"Missing required config keys: {missing}"
            raise BacktestConfigError(msg)

        # date vocabulary 검증 (#2035). required 검사가 start_date/
        # end_date 존재를 보장하므로 여기서는 ISO-8601(YYYY-MM-DD) shape·
        # 실재성·순서(start <= end)만 검증한다. ``_ISO_DATE_RE`` 는
        # ``20260510`` /``2026-W19-1`` 같은 non-canonical shape을 먼저
        # 거부하고, ``date.fromisoformat`` 가 ``2026-13-40`` 같은 비실재
        # 날짜를 거부한다. non-str(임의 타입)은 fullmatch 전에 차단.
        for label in ("start_date", "end_date"):
            value = config[label]
            if not isinstance(value, str) or _ISO_DATE_RE.fullmatch(value) is None:
                msg = f"Invalid {label} (expected YYYY-MM-DD): {value!r}"
                raise BacktestConfigError(msg)
            try:
                datetime.date.fromisoformat(value)
            except ValueError as e:
                msg = f"Invalid {label}: {value!r}"
                raise BacktestConfigError(msg) from e
        start = datetime.date.fromisoformat(config["start_date"])
        end = datetime.date.fromisoformat(config["end_date"])
        if start > end:
            msg = (
                f"start_date {config['start_date']!r} is after "
                f"end_date {config['end_date']!r}"
            )
            raise BacktestConfigError(msg)

        # symbol/timeframe vocabulary 검증 (#1604, core.md ``## Canonical
        # Symbol/Timeframe Vocabulary``:286 — programmatic API 행이
        # "검증 에러"를 normative로 요구). CLI(#1603)는 Click이 타입을
        # 협소화하지만 programmatic ``dict[str, Any]`` 는 임의 타입이
        # 유입되므로 모든 분기에 명시적 타입 경계를 두어 invalid를
        # ``TypeError`` 가 아닌 ``BacktestConfigError`` 로 early-fail
        # 시킨다. SSOT(`is_krx_symbol`)의 non-str→False 가드를
        # 우회하지 않도록 ``str()`` 캐스팅은 쓰지 않는다.
        # precedence: required-key → ① timeframe → ② symbols 정규화/
        # 구조/빈 → ③ KRX shape.
        #
        # #2060: ``timeframe`` 이 ``None`` (CLI ``--timeframe`` 생략 신호)
        # 이면 early vocab 검증을 deferred 한다 — load 후 ``run()`` 이
        # ``StrategyMeta.timeframe`` 로 fallback 하여 effective 값을
        # 재검증한다. 명시적(비-None) timeframe 은 기존대로 early 검증·거부.
        timeframe = config.get("timeframe", "1d")
        if timeframe is not None:
            self._validate_timeframe_vocab(timeframe)

        symbols_raw = config.get("symbols", [])
        # None/누락/[] → [] (no-symbols backtest 정상, 미거부). 명시적
        # ``{"symbols": None}`` 도 여기서 ``[]`` 로 정규화하여 build
        # 라인이 ``BacktestConfig.symbols=None`` 으로 새지 않게 한다.
        normalized_symbols = [] if symbols_raw is None else symbols_raw

        # exchange canonical 검증 (#2034, core.md ``## Canonical Exchange
        # Vocabulary`` / D-016). CLI(#1576)는 ingress에서 거부하지만
        # programmatic dict는 임의 값이 유입되므로 KRX-shape 블록이
        # exchange를 읽기 **전에** canonical 5종(SSOT ``is_canonical``)을
        # 강제한다. ``*`` 는 ``StrategyMeta.exchange`` 전용 wildcard라
        # ``is_canonical("*") is False`` → 거부. non-str도 거부.
        exchange = config.get("exchange", "KRX")
        if not isinstance(exchange, str) or not is_canonical(exchange):
            msg = (
                f"Invalid exchange: {exchange!r}. "
                f"Allowed: {', '.join(sorted(CANONICAL_EXCHANGES))}"
            )
            raise BacktestConfigError(msg)

        # symbols 구조/빈/KRX-shape 검증 (단일 helper — #2060 effective
        # 재검증과 동일 로직 공유). exchange == KRX 일 때만 shape 검증.
        self._validate_symbols_vocab(normalized_symbols, exchange, raw=symbols_raw)

        # numeric 검증 (#2036). config에 **존재하는** 숫자 키만 검사하고
        # 미존재는 BacktestConfig 기본값(valid)을 따른다. bool은 int의
        # subclass라 명시적으로 제외한다. initial_balance는 양수·유한,
        # 각 rate는 음수가 아닌 유한값이어야 한다 (CLI
        # validate_positive_finite_amount/validate_nonnegative_finite_amount
        # 와 동형).
        def _check_number(label: str, value: object, *, allow_zero: bool) -> None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                msg = f"Invalid {label} (expected number): {value!r}"
                raise BacktestConfigError(msg)
            if math.isnan(value) or math.isinf(value):
                msg = f"Invalid {label} (NaN/Infinity not allowed): {value!r}"
                raise BacktestConfigError(msg)
            if allow_zero and value < 0:
                msg = f"Invalid {label} (must be >= 0): {value!r}"
                raise BacktestConfigError(msg)
            if not allow_zero and value <= 0:
                msg = f"Invalid {label} (must be > 0): {value!r}"
                raise BacktestConfigError(msg)

        if "initial_balance" in config:
            _check_number(
                "initial_balance", config["initial_balance"], allow_zero=False
            )
        for _rate in ("buy_commission_rate", "sell_commission_rate", "slippage_rate"):
            if _rate in config:
                _check_number(_rate, config[_rate], allow_zero=True)

        data_paths = config.get(
            "data_paths",
            [config.get("data_path", self._data_path)],
        )

        # #2060: timeframe 이 None (CLI 생략 신호) 이면 BacktestConfig.timeframe
        # (타입 ``str``) 에 None 이 새지 않도록 placeholder "1d" 로 채운다.
        # 실제 effective timeframe 은 ``run()`` 이 load 후 ``StrategyMeta``
        # 로 resolve·재검증하여 downstream(provider/executor/result.config)
        # 에 흘릴 effective ``BacktestConfig`` 를 다시 구성한다. None 은
        # ``run()`` 로컬에서만 "생략" 신호로 쓰이고 dataclass 로는 새지 않는다.
        cfg_timeframe = config.get("timeframe", "1d")
        return BacktestConfig(
            strategy_path=config["strategy_path"],
            symbols=normalized_symbols,
            timeframe="1d" if cfg_timeframe is None else cfg_timeframe,
            exchange=config.get("exchange", "KRX"),
            start_date=config.get("start_date", ""),
            end_date=config.get("end_date", ""),
            initial_balance=config.get("initial_balance", 10_000_000.0),
            buy_commission_rate=config.get(
                "buy_commission_rate",
                config.get("commission_rate", 0.00015),
            ),
            sell_commission_rate=config.get("sell_commission_rate", 0.00195),
            slippage_rate=config.get("slippage_rate", 0.001),
            data_paths=data_paths,
        )
