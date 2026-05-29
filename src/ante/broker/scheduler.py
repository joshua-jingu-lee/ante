"""ReconcileScheduler — 주기적 자동 대사 스케줄러.

설정된 간격(기본 30분)으로 모든 활성 봇의 포지션 대사를 수행한다.
봇 시작 시 1회 대사도 지원한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.bot.manager import BotManager
    from ante.broker.base import BrokerAdapter
    from ante.eventbus.bus import EventBus
    from ante.trade.reconciler import PositionReconciler

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 1800  # 30분


class ReconcileScheduler:
    """주기적으로 모든 활성 봇의 포지션 대사를 수행한다.

    이 스케줄러 인스턴스는 단일 broker(``broker_account_id``)에만 바인딩된다.
    SPLIT-1 단계에서는 multi-account broker pool이 도입되지 않으므로,
    다른 계좌의 봇이 같은 스케줄러에 잡히는 경우 잘못된 broker positions가
    적용되지 않도록 ``run_once()`` 안에서 명시적으로 skip한다.
    multi-broker pool은 SPLIT-3에서 도입한다.

    Args:
        reconciler: 포지션 대사 실행기.
        broker: 브로커 어댑터 (실제 잔고 조회용).
        bot_manager: 활성 봇 목록 조회용.
        eventbus: 이벤트 발행용.
        broker_account_id: 이 스케줄러가 바인딩된 broker의 account_id.
            ``run_once()``는 이 account_id에 일치하는 봇만 reconcile한다.
        interval_seconds: 대사 반복 주기 (초). 기본 1800(30분).
        skip_initial_external_buy: True 면 ``start()`` 의 **기동 즉시 1회 대사**
            에서만 "외부 매수" 분류 보정을 건너뛴다(#1946 Finding 1 barrier).
            계좌의 fill 카치업이 성공하지 못한 채 기동 reconcile 이 돌면 미복구
            ante 체결을 "외부 매수" 로 오분류하므로, 그 1회만 연기한다. 이후
            주기 대사는 fill 폴 루프가 복구를 진행하므로 정상 처리한다.
    """

    def __init__(
        self,
        reconciler: PositionReconciler,
        broker: BrokerAdapter,
        bot_manager: BotManager,
        eventbus: EventBus,
        *,
        broker_account_id: str,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        skip_initial_external_buy: bool = False,
    ) -> None:
        if not broker_account_id:
            raise ValueError(
                "ReconcileScheduler requires a non-empty broker_account_id"
            )
        self._reconciler = reconciler
        self._broker = broker
        self._bot_manager = bot_manager
        self._eventbus = eventbus
        self._broker_account_id = broker_account_id
        self._interval = interval_seconds
        self._skip_initial_external_buy = skip_initial_external_buy
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """대사 스케줄러를 시작한다. 시작 즉시 1회 대사를 수행한다."""
        if self._task and not self._task.done():
            logger.warning("ReconcileScheduler 이미 실행 중")
            return

        logger.info(
            "ReconcileScheduler 시작 (주기: %d초)",
            int(self._interval),
        )
        # 기동 즉시 대사. fill 카치업 미성공 계좌는 이 1회만 external-buy 분류를
        # 연기한다(barrier). 이후 주기 루프(_loop)는 fill 복구가 진행되므로
        # 정상 처리(skip 안 함).
        await self.run_once(skip_external_buy=self._skip_initial_external_buy)
        self._task = asyncio.create_task(
            self._loop(),
            name="reconcile-scheduler",
        )

    async def stop(self) -> None:
        """스케줄러를 중지한다."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("ReconcileScheduler 종료")

    async def run_once(
        self, *, skip_external_buy: bool = False
    ) -> list[dict[str, Any]]:
        """1회 대사를 수행하고 보정 내역을 반환한다.

        모든 활성(running) 봇에 대해 브로커 포지션을 조회하고,
        PositionReconciler.reconcile()을 호출하여 불일치를 보정한다.

        Args:
            skip_external_buy: True 면 "외부 매수" 분류 보정을 건너뛴다(barrier,
                #1946 Finding 1). fill 카치업 미성공 시 기동 대사에만 쓰인다.

        Returns:
            각 봇별 보정 내역을 합산한 리스트.
        """
        from ante.bot.config import BotStatus

        all_corrections: list[dict[str, Any]] = []

        bots = self._bot_manager.list_bots()
        active_bots = [b for b in bots if b.get("status") == BotStatus.RUNNING]

        if not active_bots:
            logger.debug("대사 대상 활성 봇 없음")
            return all_corrections

        try:
            broker_positions = await self._broker.get_account_positions()
        except Exception:
            logger.exception("대사 중 브로커 포지션 조회 실패")
            return all_corrections

        for bot_info in active_bots:
            bot_id = bot_info["bot_id"]
            account_id = bot_info.get("account_id")
            if not account_id:
                logger.warning(
                    "대사 스킵: bot=%s account_id 누락 (DB 정리 필요)",
                    bot_id,
                )
                continue
            if account_id != self._broker_account_id:
                # SPLIT-1 가드: 이 스케줄러는 단일 broker(self._broker_account_id)
                # 에 바인딩돼 있다. 다른 계좌의 봇에 이 broker의 positions를
                # 적용하면 데이터 정합성이 깨지므로 명시적으로 skip한다.
                # SPLIT-3에서 multi-broker pool 도입 시 이 가드를 제거한다.
                logger.warning(
                    "대사 스킵: scheduler is bound to %s; "
                    "bot %s belongs to %s — "
                    "skipping until SPLIT-3 multi-broker pool",
                    self._broker_account_id,
                    bot_id,
                    account_id,
                )
                continue
            try:
                corrections = await self._reconciler.reconcile(
                    bot_id=bot_id,
                    broker_positions=broker_positions,
                    account_id=account_id,
                    skip_external_buy=skip_external_buy,
                )
                all_corrections.extend(corrections)
            except Exception:
                logger.exception("대사 실패 [%s]", bot_id)

        if all_corrections:
            logger.info(
                "주기 대사 완료: 활성 봇 %d개, 보정 %d건",
                len(active_bots),
                len(all_corrections),
            )
        else:
            logger.debug(
                "주기 대사 완료: 활성 봇 %d개, 불일치 없음",
                len(active_bots),
            )

        return all_corrections

    async def _loop(self) -> None:
        """interval 간격으로 run_once()를 반복 호출한다."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ReconcileScheduler 루프 오류")
