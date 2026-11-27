"""TelegramCommandReceiver — 텔레그램 명령 수신 및 실행."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, cast

from ante.account.errors import (
    AccountActivateAllFailedError,
    AccountSuspendAllFailedError,
)
from ante.core import clock
from ante.notification.telegram import TELEGRAM_REQUEST_TIMEOUT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ante.account.service import AccountService
    from ante.approval.service import ApprovalService
    from ante.bot.manager import BotManager
    from ante.instrument.service import InstrumentService
    from ante.notification.telegram import TelegramAdapter
    from ante.treasury.manager import TreasuryManager

logger = logging.getLogger(__name__)

_DANGEROUS_COMMANDS = {"halt", "clear_halt", "stop"}

_UPDATE_FAILURE_REPLY = (
    "⚠️ 처리 중 오류가 발생했습니다. "
    "명령이 일부 실행되었을 수 있으니 /status·/bots로 상태를 확인해 주세요."
)


_PROCESSING_ANSWER = "⏳ 처리 중입니다"


@dataclass(frozen=True)
class _Job:
    """작업자의 한 건과 회신 chat, 전체 정지가 버릴 때의 안내(없으면 남긴다)."""

    chat_id: int | None
    run: Callable[[], Awaitable[str]]
    dropped_notice: str | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    """dict가 아니면 빈 dict로 바꾼다."""
    return value if isinstance(value, dict) else {}


class TelegramCommandReceiver:
    """텔레그램 getUpdates 폴링으로 명령을 수신하고 실행한다."""

    def __init__(
        self,
        adapter: TelegramAdapter,
        *,
        allowed_user_ids: list[int] | None = None,
        polling_interval: float = 3.0,
        confirm_timeout: float = 30.0,
        bot_manager: BotManager | None = None,
        treasury_manager: TreasuryManager | None = None,
        account_service: AccountService | None = None,
        approval_service: ApprovalService | None = None,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._adapter = adapter
        self._allowed_user_ids = set(allowed_user_ids or [])
        self._polling_interval = polling_interval
        self._confirm_timeout = confirm_timeout
        self._bot_manager = bot_manager
        self._treasury_manager = treasury_manager
        self._account_service = account_service
        self._approval_service = approval_service
        self._instrument_service = instrument_service

        self._offset: int = 0
        self._task: asyncio.Task[None] | None = None
        self._running = False

        self._pending_confirm: dict[int, tuple[str, list[str], float]] = {}

        self._jobs: asyncio.Queue[_Job] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._dropped_on_cancel = 0

    def start(self) -> None:
        """폴링 루프 시작."""
        if not self._allowed_user_ids:
            logger.info("텔레그램 명령 수신 비활성화 — allowed_user_ids 비어있음")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("텔레그램 명령 수신 시작 (%.1f초 간격)", self._polling_interval)

    async def stop(self) -> None:
        """폴링 루프 중지."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None
        dropped = len(self._take_queued_jobs()) + self._dropped_on_cancel
        self._dropped_on_cancel = 0
        if dropped:
            logger.warning("텔레그램 작업 %d건을 실행하지 않고 버렸습니다", dropped)
        logger.info("텔레그램 명령 수신 중지")

    def _enqueue(self, job: _Job) -> None:
        """작업을 줄에 넣고 작업자가 없으면 띄운다."""
        self._jobs.put_nowait(job)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    def _take_queued_jobs(self) -> list[_Job]:
        """줄에서 아직 시작하지 않은 작업을 모두 꺼낸다."""
        jobs: list[_Job] = []
        while True:
            try:
                jobs.append(self._jobs.get_nowait())
            except asyncio.QueueEmpty:
                return jobs
            self._jobs.task_done()

    async def _work(self) -> None:
        """줄의 작업을 도착 순서대로 하나씩 실행하고, 취소 요청을 받으면 끝난다."""
        current = asyncio.current_task()
        while current is not None and not current.cancelling():
            job = await self._jobs.get()
            try:
                await self._run_job(job)
            except Exception:
                logger.exception("텔레그램 작업 회신 실패")
            finally:
                self._jobs.task_done()

    async def _run_job(self, job: _Job) -> None:
        """작업을 실행하고 결과나 실패 문구를 그 chat에 회신한다."""
        try:
            reply = await job.run()
        except Exception:
            logger.exception("텔레그램 작업 실행 실패")
            reply = _UPDATE_FAILURE_REPLY
        if reply:
            await self._reply(job.chat_id, reply)

    async def _poll_loop(self) -> None:
        """getUpdates 폴링 루프."""
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    try:
                        await self._handle_update(update)
                    except Exception:
                        logger.exception(
                            "텔레그램 업데이트 처리 실패: update_id=%s",
                            update.get("update_id")
                            if isinstance(update, dict)
                            else None,
                        )
                        await self._reply_update_failure(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("텔레그램 폴링 실패, 다음 주기에 재시도", exc_info=True)

            await asyncio.sleep(self._polling_interval)

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Telegram Bot API getUpdates 호출."""
        try:
            import aiohttp
        except ImportError:
            return []

        url = f"{self._adapter._api_base}/getUpdates"
        params: dict[str, Any] = {
            "offset": self._offset,
            "timeout": 1,
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TELEGRAM_REQUEST_TIMEOUT)
            ) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    if not data.get("ok"):
                        return []
                    results: list[dict[str, Any]] = data.get("result", [])
                    if results:
                        self._offset = results[-1]["update_id"] + 1
                    return results
        except Exception:
            logger.warning("getUpdates 호출 실패", exc_info=True)
            return []

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """개별 업데이트 처리."""
        if "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
            return

        message = update.get("message")
        if not message:
            return

        text = message.get("text", "").strip()
        if not text or not text.startswith("/"):
            return

        user = message.get("from", {})
        user_id = user.get("id", 0)
        chat_id = message.get("chat", {}).get("id")

        if not self._is_authorized(user_id):
            logger.warning(
                "미인가 텔레그램 명령 시도: user_id=%d, text=%s",
                user_id,
                text,
            )
            return

        parts = text.split()
        command = parts[0][1:].lower()
        args = parts[1:]

        reply = await self._execute(command, args, user_id, chat_id)
        if reply:
            await self._reply(chat_id, reply)

    async def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        """인라인 버튼 콜백 처리 (결재 승인/거절)."""
        callback_id = callback_query.get("id", "")
        user = callback_query.get("from", {})
        user_id = user.get("id", 0)
        chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
        data = callback_query.get("data", "")

        if not self._is_authorized(user_id):
            logger.warning("미인가 콜백 시도: user_id=%d, data=%s", user_id, data)
            await self._adapter.answer_callback_query(callback_id, "권한이 없습니다.")
            return

        if not self._approval_service:
            await self._adapter.answer_callback_query(
                callback_id, "ApprovalService가 연결되지 않았습니다."
            )
            return

        if ":" not in data:
            await self._adapter.answer_callback_query(callback_id, "잘못된 요청입니다.")
            return

        action, approval_id = data.split(":", 1)
        if action not in ("approve", "reject"):
            await self._adapter.answer_callback_query(
                callback_id, "알 수 없는 동작입니다."
            )
            return

        self._enqueue(
            _Job(
                chat_id=chat_id,
                run=partial(self._resolve_approval, action, approval_id),
                dropped_notice=(
                    "ℹ️ 전체 거래 중지 요청으로 실행하지 않았습니다 — "
                    f"결재는 대기 상태입니다\nID: {approval_id}"
                ),
            )
        )
        try:
            await self._adapter.answer_callback_query(callback_id, _PROCESSING_ANSWER)
        except Exception:
            logger.exception("텔레그램 콜백 처리 중 응답 실패: %s", data)

    async def _resolve_approval(self, action: str, approval_id: str) -> str:
        """결재를 승인하거나 거절하고 결과 문구를 돌려준다."""
        if self._approval_service is None:
            return "ApprovalService가 연결되지 않았습니다."
        try:
            if action == "approve":
                request = await self._approval_service.approve(
                    approval_id,
                    resolved_by="telegram",
                    suppress_notification=True,
                )
                if request.status == "execution_failed":
                    detail = ""
                    for entry in reversed(request.history):
                        if entry.get("action") == "execution_failed":
                            detail = entry.get("detail", "")
                            break
                    return (
                        f"⚠️ 승인되었으나 실행 실패\n"
                        f"제목: {request.title}\n"
                        f"ID: {approval_id}\n"
                        f"사유: {detail}"
                    )
                return f"✅ 결재 승인 완료\n제목: {request.title}\nID: {approval_id}"
            request = await self._approval_service.reject(
                approval_id,
                resolved_by="telegram",
                reject_reason="사용자 거절",
                suppress_notification=True,
            )
            return (
                f"❌ 결재 거절 완료\n"
                f"제목: {request.title}\n"
                f"ID: {approval_id}\n"
                f"사유: 사용자 거절"
            )
        except ValueError as e:
            err = str(e)
            if "찾을 수 없음" in err:
                return f"❌ 결재를 찾을 수 없습니다\nID: {approval_id}"
            if "만료" in err:
                return f"ℹ️ 만료된 결재입니다\nID: {approval_id}"
            return f"ℹ️ 이미 처리된 결재입니다 ({err})\nID: {approval_id}"
        except Exception:
            logger.exception("콜백 결재 처리 오류: %s:%s", action, approval_id)
            return "처리 중 오류가 발생했습니다."

    async def _reply_update_failure(self, update: Any) -> None:
        """예외로 끝난 업데이트의 허용 사용자에게 원인 없는 실패 답을 보낸다."""
        try:
            await self._send_update_failure(update)
        except Exception:
            logger.exception("텔레그램 실패 답 전송 실패")

    async def _send_update_failure(self, update: Any) -> None:
        """메시지면 그 chat에, 콜백이면 콜백 응답과 그 chat에 실패 문구를 보낸다."""
        callback = _as_dict(update).get("callback_query")
        if callback is None:
            source = _as_dict(_as_dict(update).get("message"))
        else:
            source = _as_dict(callback)
        if not self._is_authorized(_as_dict(source.get("from")).get("id", 0)):
            return
        if callback is not None:
            await self._adapter.answer_callback_query(
                source.get("id", ""), _UPDATE_FAILURE_REPLY
            )
            source = _as_dict(source.get("message"))
        await self._reply(_as_dict(source.get("chat")).get("id"), _UPDATE_FAILURE_REPLY)

    def _is_authorized(self, user_id: int) -> bool:
        """화이트리스트 인증 확인."""
        return user_id in self._allowed_user_ids

    async def _execute(
        self,
        command: str,
        args: list[str],
        user_id: int,
        chat_id: int | None,
    ) -> str:
        """명령 실행 후 결과 문자열 반환."""
        if command == "confirm":
            return await self._handle_confirm(user_id, chat_id)

        if command in _DANGEROUS_COMMANDS:
            if command == "halt" and self._account_service:
                all_suspended = await self._all_accounts_suspended()
                if all_suspended:
                    return "이미 거래가 중지된 상태입니다."
            if command == "clear_halt" and self._account_service:
                all_active = await self._all_accounts_active()
                if all_active:
                    return "이미 거래가 활성 상태입니다."
            return self._request_confirmation(command, args, user_id)

        handlers: dict[str, Any] = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "bots": self._cmd_bots,
            "balance": self._cmd_balance,
        }

        handler = handlers.get(command)
        if handler:
            result = handler(args)
            if isawaitable(result):
                return cast("str", await result)
            return cast("str", result)

        return "알 수 없는 명령입니다. /help를 입력해 주세요."

    def _request_confirmation(self, command: str, args: list[str], user_id: int) -> str:
        """위험 명령에 대한 확인 요청."""
        self._pending_confirm[user_id] = (command, args, clock.monotonic())

        if command == "halt":
            reason = " ".join(args) if args else ""
            detail = f" (사유: {reason})" if reason else ""
            return (
                f"전체 거래를 중지합니다{detail}. 확인하려면 /confirm 을 입력해 주세요."
            )
        if command == "clear_halt":
            return (
                "전역 정지를 해제합니다 (계좌 상태만 ACTIVE로 복구; 봇은 자동 "
                "재시작되지 않음). 확인하려면 /confirm 을 입력해 주세요."
            )
        if command == "stop":
            bot_id = args[0] if args else "?"
            return f"{bot_id}을 중지합니다. 확인하려면 /confirm 을 입력해 주세요."

        return "확인하려면 /confirm 을 입력해 주세요."

    async def _handle_confirm(self, user_id: int, chat_id: int | None = None) -> str:
        """확인 처리."""
        pending = self._pending_confirm.pop(user_id, None)
        if not pending:
            return "확인 대기 중인 명령이 없습니다."

        command, args, timestamp = pending
        elapsed = clock.monotonic() - timestamp

        if elapsed > self._confirm_timeout:
            return "확인 시간이 초과되었습니다."

        if command == "halt":
            return await self._cmd_halt(args)
        if command == "clear_halt":
            return await self._cmd_clear_halt(args)
        if command == "stop":
            self._enqueue(_Job(chat_id=chat_id, run=partial(self._cmd_stop, args)))
            return ""

        return "알 수 없는 명령입니다."

    async def _all_accounts_suspended(self) -> bool:
        """모든 계좌가 SUSPENDED이고 DB에 기록되지 않은 정지가 없는지 확인."""
        if not self._account_service:
            return False
        from ante.account.models import AccountStatus

        accounts = await self._account_service.list()
        if not accounts:
            return False
        if self._account_service.has_unpersisted_suspensions():
            return False
        return all(a.status == AccountStatus.SUSPENDED for a in accounts)

    async def _all_accounts_active(self) -> bool:
        """모든 계좌가 ACTIVE 상태인지 확인."""
        if not self._account_service:
            return False
        from ante.account.models import AccountStatus

        accounts = await self._account_service.list()
        if not accounts:
            return False
        return all(a.status == AccountStatus.ACTIVE for a in accounts)

    def _cmd_help(self, args: list[str]) -> str:
        """사용 가능한 명령어 목록."""
        return (
            "사용 가능한 명령어:\n"
            "/status — 시스템 상태 요약\n"
            "/bots — 봇 목록 + 상태\n"
            "/balance — 자금 현황 요약\n"
            "/halt [reason] — 전체 거래 중지 (확인 필요)\n"
            "/clear_halt — 전역 정지 해제 (확인 필요; 봇은 자동 재시작되지 않음)\n"
            "/stop <bot_id> — 특정 봇 중지 (확인 필요)\n"
            "/help — 이 도움말"
        )

    async def _cmd_status(self, args: list[str]) -> str:
        """시스템 상태 요약."""
        parts = []

        if self._account_service:
            from ante.account.models import AccountStatus

            accounts = await self._account_service.list()
            suspended = [a for a in accounts if a.status == AccountStatus.SUSPENDED]
            if suspended:
                parts.append("거래 상태: suspended")
            else:
                parts.append("거래 상태: active")

        if self._bot_manager:
            bots = self._bot_manager.list_bots()
            running = sum(1 for b in bots if b["status"] == "running")
            parts.append(f"봇: {running}/{len(bots)} 실행 중")

        if not parts:
            return "시스템 정보를 조회할 수 없습니다."

        return "\n".join(parts)

    _STATUS_KO: dict[str, str] = {
        "created": "생성됨",
        "running": "실행 중",
        "stopping": "중지 중",
        "stopped": "중지됨",
        "error": "에러",
        "deleted": "삭제됨",
    }

    def _cmd_bots(self, args: list[str]) -> str:
        """봇 목록."""
        if not self._bot_manager:
            return "BotManager가 연결되지 않았습니다."

        bots = self._bot_manager.list_bots()
        if not bots:
            return "등록된 봇이 없습니다."

        running = sum(1 for b in bots if b["status"] == "running")
        total = len(bots)

        lines = []
        for b in bots:
            status_ko = self._STATUS_KO.get(b["status"], b["status"])
            bot_id = b["bot_id"]
            strategy = b.get("strategy_id", "-")
            lines.append(f"  {bot_id} [{status_ko}] {strategy}")

        return f"\U0001f916 봇 목록 ({running}/{total} 실행 중)\n" + "\n".join(lines)

    def _cmd_balance(self, args: list[str]) -> str:
        """자금 현황 — 전 계좌 요약."""
        if not self._treasury_manager:
            return "TreasuryManager가 연결되지 않았습니다."

        treasuries = self._treasury_manager.list_all()
        if not treasuries:
            return "등록된 계좌가 없습니다."

        sections: list[str] = []
        for treasury in treasuries:
            sections.append(
                f"계좌: {treasury.account_id}\n"
                + self._render_account_balance(treasury.get_summary())
            )

        return "ℹ️ 자금 현황\n\n" + "\n\n".join(sections)

    @staticmethod
    def _render_account_balance(summary: dict[str, Any]) -> str:
        """단일 계좌 자금 현황 본문 렌더링 (타이틀 제외)."""
        balance = summary.get("account_balance", 0)
        purchasable = summary.get("purchasable_amount", 0)
        ante_purchase = summary.get("ante_purchase_amount", 0)
        ante_eval = summary.get("ante_eval_amount", 0)
        ante_pl = summary.get("ante_profit_loss", 0)
        allocated = summary.get("total_allocated", 0)
        unallocated = summary.get("unallocated", 0)
        bot_count = summary.get("bot_count", 0)

        if ante_pl > 0:
            pl_sign = "+"
            pl_emoji = "📈"
        elif ante_pl < 0:
            pl_sign = ""
            pl_emoji = "📉"
        else:
            pl_sign = ""
            pl_emoji = "➖"

        lines = [
            f"계좌 예수금: {balance:,.0f}원",
            f"매수 가능: {purchasable:,.0f}원",
        ]

        if ante_purchase > 0:
            lines.append("")
            lines.append(
                f"{pl_emoji} Ante 관리 종목\n"
                f"  매입: {ante_purchase:,.0f}원 → "
                f"평가: {ante_eval:,.0f}원 ({pl_sign}{ante_pl:,.0f}원)"
            )

        lines.append("")
        lines.append(f"봇 할당: {allocated:,.0f}원 ({bot_count}개)")
        lines.append(f"미할당: {unallocated:,.0f}원")

        return "\n".join(lines)

    async def _cmd_halt(self, args: list[str]) -> str:
        """전체 거래 중지."""
        if not self._account_service:
            return "AccountService가 연결되지 않았습니다."

        all_suspended = await self._all_accounts_suspended()
        if all_suspended:
            return "이미 거래가 중지된 상태입니다."

        reason = " ".join(args) if args else "텔레그램 명령"
        taken = self._take_queued_jobs()
        try:
            await self._account_service.suspend_all(
                reason=reason,
                suspended_by="telegram",
            )
        except AccountSuspendAllFailedError as exc:
            return (
                f"⚠️ 전체 거래 중지가 일부 계좌에서 실패했습니다.\n{exc}\n사유: {reason}"
            )
        except asyncio.CancelledError:
            self._dropped_on_cancel += len(taken)
            taken = []
            raise
        finally:
            await self._requeue_or_drop(taken)
        return (
            "\U0001f6a8 전체 거래가 중지되었습니다.\n"
            f"사유: {reason}\n"
            "해제하려면 /clear_halt 를 입력하세요."
        )

    async def _requeue_or_drop(self, jobs: list[_Job]) -> None:
        """안내가 없는 작업은 순서대로 줄에 되돌리고, 나머지는 버리며 안내한다."""
        for job in jobs:
            if job.dropped_notice is None:
                self._enqueue(job)
        dropped = [job for job in jobs if job.dropped_notice is not None]
        for sent, job in enumerate(dropped):
            try:
                await self._reply(job.chat_id, cast("str", job.dropped_notice))
            except asyncio.CancelledError:
                self._dropped_on_cancel += len(dropped) - sent
                raise
            except Exception:
                logger.exception("텔레그램 버린 작업 안내 실패")

    async def _cmd_clear_halt(self, args: list[str]) -> str:
        """전역 정지 해제 (계좌 상태만 ACTIVE 복구; 봇 자동 재시작 없음)."""
        if not self._account_service:
            return "AccountService가 연결되지 않았습니다."

        if await self._all_accounts_active():
            return "이미 거래가 활성 상태입니다."

        try:
            await self._account_service.activate_all(activated_by="telegram")
        except AccountActivateAllFailedError as exc:
            return f"⚠️ 전역 정지 해제가 중간에 멈췄습니다.\n{exc}"
        return (
            "✅ 전역 정지가 해제되었습니다.\n"
            "계좌 상태만 ACTIVE로 복구되며 봇은 자동 재시작되지 않습니다."
        )

    async def _cmd_stop(self, args: list[str]) -> str:
        """특정 봇 중지."""
        from ante.bot.config import BotStatus

        if not self._bot_manager:
            return "BotManager가 연결되지 않았습니다."

        if not args:
            return "봇 ID를 지정해 주세요. 예: /stop bot-1"

        bot_id = args[0]
        bot = self._bot_manager.get_bot(bot_id)
        if not bot:
            return f"봇을 찾을 수 없습니다: {bot_id}"

        if bot.status != BotStatus.RUNNING:
            return f"이미 중지된 봇입니다: {bot_id}"

        positions = bot._ctx.get_positions()

        cleanup = await self._bot_manager.stop_bot(bot_id, suppress_notification=True)

        bot_name = bot.config.name or bot_id
        header = f"ℹ️ *봇 중지*\n\n봇: {bot_name} ({bot_id})\n상태: 실행 중 → 중지됨"
        lines = [header]
        if cleanup is not None:
            lines.extend(["", *cleanup.summary_lines()])

        if positions:
            symbols = sorted(positions.keys())
            held_line = await self._format_held_symbols(bot, symbols)
            lines.extend(
                [
                    "",
                    f"⚠️ 보유 종목 {len(symbols)}개가 유지됩니다.",
                    "중지 후 포지션을 직접 관리해야 합니다.",
                    "",
                    f"보유: {held_line}",
                ]
            )
        return "\n".join(lines)

    async def _format_held_symbols(self, bot: Any, symbols: list[str]) -> str:
        """보유종목 표기 라인을 구성한다."""
        if self._instrument_service is None:
            return ", ".join(symbols)

        exchange = "KRX"
        try:
            account_id = bot.config.account_id
            if account_id and self._account_service is not None:
                account = await self._account_service.get(account_id)
                exchange = account.exchange
        except Exception:
            logger.warning(
                "보유종목 exchange 해석 실패 — KRX 기본값 사용", exc_info=True
            )
            exchange = "KRX"

        return ", ".join(
            self._instrument_service.format_label(symbol, exchange, markdown=False)
            for symbol in symbols
        )

    async def _reply(self, chat_id: int | None, text: str) -> None:
        """메시지 회신."""
        if not chat_id:
            return
        try:
            import aiohttp
        except ImportError:
            return

        url = f"{self._adapter._api_base}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TELEGRAM_REQUEST_TIMEOUT)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning("텔레그램 회신 실패: status=%d", resp.status)
        except Exception:
            logger.warning("텔레그램 회신 오류", exc_info=True)
