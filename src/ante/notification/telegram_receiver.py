"""TelegramCommandReceiver — 텔레그램 명령 수신 및 실행."""

from __future__ import annotations

import asyncio
import logging
import time as time_mod
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.approval.service import ApprovalService
    from ante.bot.manager import BotManager
    from ante.config.system_state import SystemState
    from ante.notification.telegram import TelegramAdapter
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)

# 확인이 필요한 위험 명령
_DANGEROUS_COMMANDS = {"halt", "stop"}


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
        treasury: Treasury | None = None,
        system_state: SystemState | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._adapter = adapter
        self._allowed_user_ids = set(allowed_user_ids or [])
        self._polling_interval = polling_interval
        self._confirm_timeout = confirm_timeout
        self._bot_manager = bot_manager
        self._treasury = treasury
        self._system_state = system_state
        self._approval_service = approval_service

        self._offset: int = 0
        self._task: asyncio.Task[None] | None = None
        self._running = False

        # 2단계 확인 대기 상태: {user_id: (command, args, timestamp)}
        self._pending_confirm: dict[int, tuple[str, list[str], float]] = {}

    # ── 생명주기 ────────────────────────────────────

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
        logger.info("텔레그램 명령 수신 중지")

    # ── 폴링 루프 ───────────────────────────────────

    async def _poll_loop(self) -> None:
        """getUpdates 폴링 루프."""
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._handle_update(update)
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
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    if not data.get("ok"):
                        return []
                    results = data.get("result", [])
                    if results:
                        self._offset = results[-1]["update_id"] + 1
                    return results
        except Exception:
            logger.warning("getUpdates 호출 실패", exc_info=True)
            return []

    # ── 메시지 처리 ─────────────────────────────────

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """개별 업데이트 처리."""
        # callback_query (인라인 버튼) 처리
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

        # 인증 확인
        if not self._is_authorized(user_id):
            logger.warning(
                "미인가 텔레그램 명령 시도: user_id=%d, text=%s",
                user_id,
                text,
            )
            return

        # 명령어 파싱
        parts = text.split()
        command = parts[0][1:].lower()  # /command → command
        args = parts[1:]

        # 실행
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

        # data 형식: "approve:{id}" 또는 "reject:{id}"
        if ":" not in data:
            await self._adapter.answer_callback_query(callback_id, "잘못된 요청입니다.")
            return

        action, approval_id = data.split(":", 1)

        try:
            if action == "approve":
                await self._approval_service.approve(
                    approval_id, resolved_by="telegram"
                )
                result_msg = f"결재 승인 완료: {approval_id}"
            elif action == "reject":
                await self._approval_service.reject(
                    approval_id, resolved_by="telegram", reject_reason="사용자 거절"
                )
                result_msg = f"결재 거절 완료: {approval_id}"
            else:
                await self._adapter.answer_callback_query(
                    callback_id, "알 수 없는 동작입니다."
                )
                return
        except ValueError as e:
            result_msg = f"처리 실패: {e}"
        except Exception:
            logger.exception("콜백 결재 처리 오류: %s", data)
            result_msg = "처리 중 오류가 발생했습니다."

        await self._adapter.answer_callback_query(callback_id, result_msg)
        if chat_id:
            await self._reply(chat_id, result_msg)

    def _is_authorized(self, user_id: int) -> bool:
        """화이트리스트 인증 확인."""
        return user_id in self._allowed_user_ids

    # ── 명령 실행 ───────────────────────────────────

    async def _execute(
        self,
        command: str,
        args: list[str],
        user_id: int,
        chat_id: int | None,
    ) -> str:
        """명령 실행 후 결과 문자열 반환."""
        # /confirm 처리
        if command == "confirm":
            return await self._handle_confirm(user_id)

        # 위험 명령 → 확인 절차
        if command in _DANGEROUS_COMMANDS:
            return self._request_confirmation(command, args, user_id)

        # 즉시 실행 명령
        handlers: dict[str, Any] = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "bots": self._cmd_bots,
            "balance": self._cmd_balance,
            "activate": self._cmd_activate,
            "approve": self._cmd_approve,
            "reject": self._cmd_reject,
        }

        handler = handlers.get(command)
        if handler:
            result = handler(args)
            if isawaitable(result):
                return await result
            return result

        return "알 수 없는 명령입니다. /help를 입력해 주세요."

    # ── 확인 절차 ───────────────────────────────────

    def _request_confirmation(self, command: str, args: list[str], user_id: int) -> str:
        """위험 명령에 대한 확인 요청."""
        self._pending_confirm[user_id] = (command, args, time_mod.time())

        if command == "halt":
            reason = " ".join(args) if args else ""
            detail = f" (사유: {reason})" if reason else ""
            return (
                f"전체 거래를 중지합니다{detail}. 확인하려면 /confirm 을 입력해 주세요."
            )
        if command == "stop":
            bot_id = args[0] if args else "?"
            return f"{bot_id}을 중지합니다. 확인하려면 /confirm 을 입력해 주세요."

        return "확인하려면 /confirm 을 입력해 주세요."

    async def _handle_confirm(self, user_id: int) -> str:
        """확인 처리."""
        pending = self._pending_confirm.pop(user_id, None)
        if not pending:
            return "확인 대기 중인 명령이 없습니다."

        command, args, timestamp = pending
        elapsed = time_mod.time() - timestamp

        if elapsed > self._confirm_timeout:
            return "확인 시간이 초과되었습니다."

        # 실제 실행
        if command == "halt":
            return await self._cmd_halt(args)
        if command == "stop":
            return await self._cmd_stop(args)

        return "알 수 없는 명령입니다."

    # ── 명령 핸들러 ─────────────────────────────────

    def _cmd_help(self, args: list[str]) -> str:
        """사용 가능한 명령어 목록."""
        return (
            "사용 가능한 명령어:\n"
            "/status — 시스템 상태 요약\n"
            "/bots — 봇 목록 + 상태\n"
            "/balance — 자금 현황 요약\n"
            "/halt [reason] — 전체 거래 중지 (확인 필요)\n"
            "/activate — 거래 재개\n"
            "/stop <bot_id> — 특정 봇 중지 (확인 필요)\n"
            "/approve <id> — 결재 승인\n"
            "/reject <id> [reason] — 결재 거절\n"
            "/help — 이 도움말"
        )

    def _cmd_status(self, args: list[str]) -> str:
        """시스템 상태 요약."""
        parts = []

        if self._system_state:
            state = self._system_state.trading_state
            parts.append(f"거래 상태: {state.value}")

        if self._bot_manager:
            bots = self._bot_manager.list_bots()
            running = sum(1 for b in bots if b["status"] == "running")
            parts.append(f"봇: {running}/{len(bots)} 실행 중")

        if not parts:
            return "시스템 정보를 조회할 수 없습니다."

        return "\n".join(parts)

    def _cmd_bots(self, args: list[str]) -> str:
        """봇 목록."""
        if not self._bot_manager:
            return "BotManager가 연결되지 않았습니다."

        bots = self._bot_manager.list_bots()
        if not bots:
            return "등록된 봇이 없습니다."

        lines = []
        for b in bots:
            status = b["status"]
            bot_id = b["bot_id"]
            strategy = b.get("strategy_id", "-")
            lines.append(f"  {bot_id} [{status}] {strategy}")

        return "봇 목록:\n" + "\n".join(lines)

    def _cmd_balance(self, args: list[str]) -> str:
        """자금 현황."""
        if not self._treasury:
            return "Treasury가 연결되지 않았습니다."

        summary = self._treasury.get_summary()
        balance = summary.get("account_balance", 0)
        purchasable = summary.get("purchasable_amount", 0)
        ante_purchase = summary.get("ante_purchase_amount", 0)
        ante_eval = summary.get("ante_eval_amount", 0)
        ante_pl = summary.get("ante_profit_loss", 0)
        allocated = summary.get("total_allocated", 0)
        unallocated = summary.get("unallocated", 0)
        bot_count = summary.get("bot_count", 0)

        # 손익 부호 및 이모지
        if ante_pl > 0:
            pl_sign = "+"
            pl_emoji = "📈"
        elif ante_pl < 0:
            pl_sign = ""  # 음수는 자동으로 - 붙음
            pl_emoji = "📉"
        else:
            pl_sign = ""
            pl_emoji = "➖"

        lines = [
            "ℹ️ 자금 현황",
            f"계좌 예수금: {balance:,.0f}원",
            f"매수 가능: {purchasable:,.0f}원",
        ]

        # Ante 관리 종목 (매입금이 있을 때만 표시)
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

    async def _cmd_approve(self, args: list[str]) -> str:
        """결재 승인. /approve <id>"""
        if not self._approval_service:
            return "ApprovalService가 연결되지 않았습니다."
        if not args:
            return "결재 ID를 지정해 주세요. 예: /approve abc123"

        approval_id = args[0]
        try:
            await self._approval_service.approve(approval_id, resolved_by="telegram")
            return f"결재 승인 완료: {approval_id}"
        except ValueError as e:
            return f"승인 실패: {e}"
        except Exception:
            logger.exception("결재 승인 오류: %s", approval_id)
            return "승인 처리 중 오류가 발생했습니다."

    async def _cmd_reject(self, args: list[str]) -> str:
        """결재 거절. /reject <id> [reason]"""
        if not self._approval_service:
            return "ApprovalService가 연결되지 않았습니다."
        if not args:
            return "결재 ID를 지정해 주세요. 예: /reject abc123 사유"

        approval_id = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "사용자 거절"
        try:
            await self._approval_service.reject(
                approval_id, resolved_by="telegram", reject_reason=reason
            )
            return f"결재 거절 완료: {approval_id} (사유: {reason})"
        except ValueError as e:
            return f"거절 실패: {e}"
        except Exception:
            logger.exception("결재 거절 오류: %s", approval_id)
            return "거절 처리 중 오류가 발생했습니다."

    async def _cmd_halt(self, args: list[str]) -> str:
        """전체 거래 중지."""
        if not self._system_state:
            return "SystemState가 연결되지 않았습니다."

        from ante.config.system_state import TradingState

        reason = " ".join(args) if args else "텔레그램 명령"
        await self._system_state.set_state(
            TradingState.HALTED, reason=reason, changed_by="telegram"
        )
        return f"전체 거래가 중지되었습니다. (사유: {reason})"

    async def _cmd_activate(self, args: list[str]) -> str:
        """거래 재개."""
        if not self._system_state:
            return "SystemState가 연결되지 않았습니다."

        from ante.config.system_state import TradingState

        await self._system_state.set_state(
            TradingState.ACTIVE, reason="텔레그램 명령", changed_by="telegram"
        )
        return "거래가 재개되었습니다."

    async def _cmd_stop(self, args: list[str]) -> str:
        """특정 봇 중지."""
        if not self._bot_manager:
            return "BotManager가 연결되지 않았습니다."

        if not args:
            return "봇 ID를 지정해 주세요. 예: /stop bot-1"

        bot_id = args[0]
        bot = self._bot_manager.get_bot(bot_id)
        if not bot:
            return f"봇을 찾을 수 없습니다: {bot_id}"

        await self._bot_manager.stop_bot(bot_id)
        return f"봇 {bot_id}이 중지되었습니다."

    # ── 유틸 ────────────────────────────────────────

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
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning("텔레그램 회신 실패: status=%d", resp.status)
        except Exception:
            logger.warning("텔레그램 회신 오류", exc_info=True)
