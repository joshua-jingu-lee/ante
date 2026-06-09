"""SignalChannelRegistry — signal.connect 채널 생명주기 권위 레지스트리 (#2334/#2337).

bot_id 당 단일 connect 정책과 daemon-위임 teardown 을 강제하는 동기 코어다.

설계 불변 (F1+F4 상태 전이표, 이슈 #2337):

- **동기 메서드는 내부에서 ``await`` 하지 않는다.** ``register``/``unregister``/
  ``close_bot``/``freeze``/``get``/``current_generation``/``bump_generation`` 는
  단일-스레드 이벤트 루프 한 틱 안에서 끊김 없이 실행된다. check↔insert 사이에
  ``await`` 가 없어야 단일-connect TOCTOU 가 닫힌다. ``close_all`` 만 async 다 —
  각 채널의 정리 task 를 await-to-completion 해야 하기 때문이며, register/
  unregister/close_bot/freeze 의 동기 계약과 분리된다(스펙 §7 reconciliation).

- **ChannelHandle 2단계 생명주기(placeholder → adopted).** ``register`` 는
  핸드셰이크 핸들러에서 ack write **전** 호출되므로, 그 시점에는 데이터플레인
  (out_queue/read_task/writer_task/on_closed/closing_event)이 아직 없다 — stream
  코루틴 진입 후 ``adopt`` 한다. placeholder 단계의 ``close(reason)`` 은 reason 만
  ``_pending_close_reason`` 으로 래치하고, adopt 가 이를 감지해 즉시 self-close
  한다. 이로써 register-and-ack-fail 또는 rotate-in-window 누수를 차단한다.

- **generation counter.** key re-validation(DB await)이 아니라 동기 카운터로
  rotate-in-window 를 결정적으로 감지한다. ``register`` 가 현재 generation 을
  스냅샷하고, adopt 시점에 ``current_generation`` 과 비교해 불일치면 self-close.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ante.bot.exceptions import BotSignalChannelBusy, SignalChannelRegistryFrozen

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class ChannelHandle:
    """단일 signal.connect 세션의 레지스트리 핸들 (#2337 F1+F4).

    register 시점(placeholder)에는 데이터플레인 4필드(``out_queue``/``read_task``/
    ``writer_task``/``on_closed``)와 ``closing_event`` 가 모두 ``None`` 이며,
    ``_run_signal_stream`` 진입 후 adopt 가 채운다.

    ``close(reason)`` 는 **동기·idempotent·non-raising** 이다. 어떤 컨텍스트
    (close_bot/rotate/delete/BotStopped/close_all/adopt self-close)에서 호출돼도
    안전하도록 ``await`` 가 없다:

    - first-wins: 이미 ``closed`` 면 ``False`` 반환(no-op).
    - ``on_closed(reason)`` 으로 channel 의 ``_closed``/``_accepting`` 을 set.
    - 데이터플레인이 있으면(adopted) ``{type:closed,reason}`` 을 out_queue 에
      force-slot 으로 enqueue(QueueFull → 1개 drop 후 재시도) + ``closing_event``
      set 으로 stream supervisor 의 async teardown(``_initiate_close``)을 깨운다.
    - 데이터플레인이 없으면(placeholder) reason 만 ``_pending_close_reason`` 에
      래치 → adopt 가 감지해 self-close.

    **strategy/ctx hard-ref 미보유** — 봇 생명주기 너머로 전략 객체를 잡지 않는다.
    """

    session_id: str
    bot_id: str
    generation: int = 0
    out_queue: asyncio.Queue[dict[str, Any]] | None = None
    read_task: asyncio.Task[Any] | None = None
    writer_task: asyncio.Task[Any] | None = None
    on_closed: Callable[[], None] | None = None
    closing_event: asyncio.Event | None = None
    closed: bool = False
    close_reason: str = ""
    _pending_close_reason: str | None = None

    def close(self, reason: str) -> bool:
        """채널을 동기·idempotent 로 닫는다. first-close-wins.

        Returns:
            첫 close 면 ``True``, 이미 닫혔으면 ``False`` (멱등 no-op).
        """
        if self.closed:
            return False
        self.closed = True
        self.close_reason = reason

        # channel 의 _closed/_accepting set (stale-publish layer2 + admit-gate).
        # on_closed 는 await-free 동기 콜백(channel.mark_closed) 이다.
        if self.on_closed is not None:
            self.on_closed()

        out_queue = self.out_queue
        if out_queue is not None:
            # adopted: closed frame 을 force-slot 으로 넣는다. QueueFull 이면
            # 가장 오래된 1개를 drop 하고 재시도 — teardown frame 은 반드시
            # 전달되어야 한다(INV-OUT-8 teardown frame 보장).
            self._force_enqueue(out_queue, {"type": "closed", "reason": reason})
            if self.closing_event is not None:
                # stream supervisor 의 async teardown 을 깨운다.
                self.closing_event.set()
        else:
            # placeholder: reason 만 래치 → adopt 가 감지해 self-close.
            self._pending_close_reason = reason
        return True

    def _force_enqueue(
        self, queue: asyncio.Queue[dict[str, Any]], frame: dict[str, Any]
    ) -> None:
        """``frame`` 을 force-slot 으로 enqueue. QueueFull 이면 1개 drop 후 재시도."""
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # 동시 producer 와의 극단 race — best-effort 로 포기(다음
                # supervisor tick 이 closing_event 로 teardown 을 진행한다).
                logger.warning("closed frame force-slot 실패: bot=%s", self.bot_id)

    # close_all join 이 supervisor 의 flush-before-cancel 를 양보하는 grace.
    JOIN_GRACE_SECONDS = 3.0

    async def join(self) -> None:
        """read_task/writer_task 가 정리될 때까지 대기 (``close_all`` 이 await).

        ``close()`` 가 ``closing_event`` 를 set 한 뒤 stream supervisor 가
        ``_initiate_close`` 로 read/writer task 를 flush-before-cancel(closed
        frame 전달 후 cancel)·join 한다(정상 경로). 본 메서드는 그 두 task 가
        **grace 안에 자연 정리되도록 먼저 await** 해 supervisor 의 closed-frame
        flush 를 양보하고(client 가 ``{closed,reason}`` 을 받음), grace 초과 시
        (supervisor 미진행 등)만 직접 cancel 후 await 한다 — close_all 이 외부
        supervisor wiring 에 의존하지 않으면서 deadlock-free 로 await-to-
        completion 하도록 보장한다(suppress CancelledError). task 가 없으면
        (placeholder, adopt 전) 즉시 반환한다.
        """
        tasks = [t for t in (self.read_task, self.writer_task) if t is not None]
        if not tasks:
            return
        # supervisor 의 flush-before-cancel 를 grace 동안 양보.
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*tasks, return_exceptions=True)),
                timeout=self.JOIN_GRACE_SECONDS,
            )
            return
        except TimeoutError:
            pass
        # grace 초과 — 직접 cancel 후 await(deadlock 회피).
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class SignalChannelRegistry:
    """bot_id 당 단일 connect + daemon-위임 teardown 의 단일 권위 레지스트리 (#2337).

    ``_sessions``: ``{bot_id: {session_id: ChannelHandle}}``. 단일-connect 정책상
    inner dict 는 최대 1개의 active handle 만 갖지만, unregister race 멱등성을 위해
    session_id 키 dict 를 유지한다.

    ``_generations``: ``{bot_id: int}``. rotate/delete teardown 이 bump 해 adopt-time
    re-check 로 rotate-in-window 핸드셰이크를 self-close 시킨다.

    ``_frozen``: shutdown sweep 진입 후 ``True`` — 이후 ``register`` 는
    ``SignalChannelRegistryFrozen`` 을 raise 해 re-register leak 을 차단한다.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, ChannelHandle]] = {}
        self._generations: dict[str, int] = {}
        self._frozen = False

    # ── 단일-connect atomic 게이트 (await 금지) ──────────────────────────

    def register(self, handle: ChannelHandle) -> None:
        """핸들을 atomic check-and-insert 로 등록한다.

        **check↔insert 사이에 ``await`` 가 없다** — 단일-connect TOCTOU 를 닫는
        권위 게이트. frozen 이면 ``SignalChannelRegistryFrozen``, 같은 bot_id 에
        이미 active session 이 있으면 ``BotSignalChannelBusy`` (둘 다 ack write
        **전** 핸드셰이크 핸들러에서 raise → Phase-B envelope, stream 미진입).
        """
        if self._frozen:
            raise SignalChannelRegistryFrozen(
                "signal channel registry is frozen (shutting down)"
            )
        bot_sessions = self._sessions.get(handle.bot_id)
        if bot_sessions:
            # 이미 active session 존재 → 단일-connect 거부.
            raise BotSignalChannelBusy()
        self._sessions[handle.bot_id] = {handle.session_id: handle}

    def has_active_session(self, bot_id: str) -> bool:
        """advisory peek — 권위 게이트는 ``register`` 의 atomic check 다."""
        return bool(self._sessions.get(bot_id))

    def get(self, bot_id: str, session_id: str) -> ChannelHandle | None:
        """등록된 핸들을 조회한다 (adopt 가 placeholder 를 회수할 때 사용)."""
        bot_sessions = self._sessions.get(bot_id)
        if not bot_sessions:
            return None
        return bot_sessions.get(session_id)

    def unregister(self, bot_id: str, session_id: str) -> None:
        """핸들을 제거한다 — **missing-key no-op** (멱등).

        ``_run_signal_stream`` finally 와 ack-fail upgrade-except 가 둘 다 호출할
        수 있으므로 missing-key 에 raise 하지 않는다. inner dict 가 비면 outer
        에서도 정리한다.
        """
        bot_sessions = self._sessions.get(bot_id)
        if not bot_sessions:
            return
        bot_sessions.pop(session_id, None)
        if not bot_sessions:
            self._sessions.pop(bot_id, None)

    # ── generation (rotate-in-window 감지) ───────────────────────────────

    def current_generation(self, bot_id: str) -> int:
        """현재 generation. register 가 스냅샷하고 adopt 가 re-check 한다."""
        return self._generations.get(bot_id, 0)

    def bump_generation(self, bot_id: str) -> None:
        """generation 을 1 증가 — rotate teardown 이 adopt-time self-close 유도."""
        self._generations[bot_id] = self._generations.get(bot_id, 0) + 1

    # ── teardown (snapshot 순회·idempotent·unregister 안 함) ──────────────

    def close_bot(self, bot_id: str, reason: str) -> int:
        """봇의 모든 active session 을 닫는다. 닫은(first-close) 개수 반환.

        **snapshot 순회** — ``list(...).values()`` 로 복사 후 각 ``close(reason)``
        를 호출한다(순회 중 dict 변형 회피). **unregister 는 하지 않는다** —
        unregister 는 각 채널의 ``_run_signal_stream`` finally 가 정확히 1회
        소유한다(INV-OUT-9). idempotent: 이미 닫힌 핸들은 ``close`` 가 ``False``
        라 count 에 포함되지 않는다.
        """
        bot_sessions = self._sessions.get(bot_id)
        if not bot_sessions:
            return 0
        count = 0
        for handle in list(bot_sessions.values()):
            if handle.close(reason):
                count += 1
        return count

    def freeze(self) -> None:
        """레지스트리를 freeze — 이후 ``register`` 는 raise (shutdown sweep)."""
        self._frozen = True

    async def close_all(self, reason: str) -> None:
        """전체 active session 을 닫고 정리 task 를 await-to-completion 한다.

        shutdown sweep 의 단독 async 메서드. 전체 핸들을 snapshot 한 뒤 각
        ``close(reason)`` (동기) 로 closed frame + closing_event 를 발화하고,
        ``gather(*join, return_exceptions=True)`` 로 read/writer task 가 모두
        정리될 때까지 await 한다 — 단순 cancel 이 아니라 grace-aware teardown
        의 완료를 기다린다(스펙 §7: query 코루틴이 db.close 너머 생존 금지).
        """
        handles: list[ChannelHandle] = [
            handle
            for bot_sessions in list(self._sessions.values())
            for handle in list(bot_sessions.values())
        ]
        for handle in handles:
            handle.close(reason)
        if handles:
            await asyncio.gather(
                *(handle.join() for handle in handles),
                return_exceptions=True,
            )
