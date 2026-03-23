"""계좌 룰 — 계좌 레벨에서 모든 봇에 적용되는 룰."""

from __future__ import annotations

from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class DailyLossLimitRule(Rule):
    """일일 손실 한도 초과 시 계좌 중지."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        max_daily_loss = self.config.get("max_daily_loss_percent", 0.05)

        if context.daily_pnl < 0 and context.prev_day_total_asset > 0:
            daily_loss_percent = abs(context.daily_pnl) / context.prev_day_total_asset

            if daily_loss_percent > max_daily_loss:
                # 매도(손절)는 항상 허용 — 포지션 정리를 차단하면 안 됨
                if context.side == "sell":
                    return RuleEvaluation(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        result=RuleResult.PASS,
                        action=RuleAction.LOG,
                        message=(
                            f"Daily loss limit exceeded "
                            f"({daily_loss_percent:.2%} > {max_daily_loss:.2%}) "
                            f"but sell order is allowed for position liquidation"
                        ),
                        metadata={
                            "daily_loss_percent": daily_loss_percent,
                            "max_daily_loss_percent": max_daily_loss,
                            "daily_pnl": context.daily_pnl,
                            "prev_day_total_asset": context.prev_day_total_asset,
                        },
                    )

                return RuleEvaluation(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    result=RuleResult.REJECT,
                    action=RuleAction.NOTIFY,
                    message=(
                        f"Daily loss limit exceeded: "
                        f"{daily_loss_percent:.2%} > {max_daily_loss:.2%}. "
                        f"Buy orders blocked. Sell orders are still allowed."
                    ),
                    metadata={
                        "daily_loss_percent": daily_loss_percent,
                        "max_daily_loss_percent": max_daily_loss,
                        "daily_pnl": context.daily_pnl,
                        "prev_day_total_asset": context.prev_day_total_asset,
                    },
                )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Daily loss within limits",
        )


class TotalExposureLimitRule(Rule):
    """총 포지션 노출 한도 초과 시 거래 제한."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        # 매도(손절)는 항상 허용 — 포지션 정리를 차단하면 안 됨
        if context.side == "sell":
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.name,
                result=RuleResult.PASS,
                action=RuleAction.LOG,
                message="Sell order is always allowed for position liquidation",
            )

        max_exposure_percent = self.config.get("max_exposure_percent", 0.20)
        max_exposure_amount = self.config.get("max_exposure_amount", float("inf"))

        order_value = context.quantity * context.current_price
        expected_exposure = context.total_exposure + order_value

        if context.total_asset > 0:
            exposure_limit = min(
                max_exposure_amount,
                context.total_asset * max_exposure_percent,
            )

            if expected_exposure > exposure_limit:
                return RuleEvaluation(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    result=RuleResult.REJECT,
                    action=RuleAction.NOTIFY,
                    message=(
                        f"Total exposure would exceed limit: "
                        f"{expected_exposure:.2f} > {exposure_limit:.2f}. "
                        f"Buy orders blocked. Sell orders are still allowed."
                    ),
                    metadata={
                        "total_exposure": context.total_exposure,
                        "expected_exposure": expected_exposure,
                        "exposure_limit": exposure_limit,
                        "total_asset": context.total_asset,
                    },
                )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Exposure within limits",
        )


class TradingHoursRule(Rule):
    """거래 허용 시간 외 거래 차단.

    테스트 용이성을 위해 현재 시각을 context.metadata["current_time"]에서
    받을 수 있다. 없으면 실제 시각을 사용한다.
    """

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        # context 필드가 기본값이 아니면 context 우선, 그렇지 않으면 config fallback
        _default_start, _default_end = "09:00", "15:30"
        context_overridden = (
            context.trading_hours_start != _default_start
            or context.trading_hours_end != _default_end
        )

        if context_overridden:
            start_str = context.trading_hours_start
            end_str = context.trading_hours_end
        else:
            # 하위 호환: config의 allowed_hours 파싱
            allowed_hours_cfg = self.config.get("allowed_hours", "")
            if allowed_hours_cfg:
                parts = allowed_hours_cfg.split("-")
                start_str = parts[0].strip() if len(parts) == 2 else _default_start
                end_str = parts[1].strip() if len(parts) == 2 else _default_end
            else:
                start_str = _default_start
                end_str = _default_end

        timezone_str = context.timezone or self.config.get("timezone", "Asia/Seoul")

        # 테스트 주입 또는 실제 시각
        now = context.metadata.get("current_time")
        if now is None:
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)

        current_time = now.time() if isinstance(now, datetime) else now

        start_time = time.fromisoformat(start_str)
        end_time = time.fromisoformat(end_str)
        allowed_hours = f"{start_str}-{end_str}"

        if not (start_time <= current_time <= end_time):
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.name,
                result=RuleResult.REJECT,
                action=RuleAction.LOG,
                message=(
                    f"Trading not allowed at {current_time.isoformat()} "
                    f"(allowed: {allowed_hours})"
                ),
                metadata={
                    "current_time": current_time.isoformat(),
                    "allowed_hours": allowed_hours,
                },
            )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Within trading hours",
        )
