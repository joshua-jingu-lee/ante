"""계좌 룰 — 계좌 레벨에서 모든 봇에 적용되는 룰."""

from __future__ import annotations

from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class DailyLossLimitRule(Rule):
    """일일 손실 한도 초과 시 계좌 중지."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        max_daily_loss = self.config.get("max_daily_loss_percent", 0.05)

        if context.daily_pnl < 0 and context.total_pnl != 0:
            daily_loss_amount = abs(context.daily_pnl)
            base = context.total_pnl + daily_loss_amount
            if base > 0:
                daily_loss_percent = daily_loss_amount / base

                if daily_loss_percent > max_daily_loss:
                    return RuleEvaluation(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        result=RuleResult.BLOCK,
                        action=RuleAction.HALT_ACCOUNT,
                        message=(
                            f"Daily loss limit exceeded: "
                            f"{daily_loss_percent:.2%} > {max_daily_loss:.2%}"
                        ),
                        metadata={
                            "daily_loss_percent": daily_loss_percent,
                            "max_daily_loss_percent": max_daily_loss,
                            "daily_pnl": context.daily_pnl,
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
        max_exposure_percent = self.config.get("max_exposure_percent", 0.20)
        max_exposure_amount = self.config.get("max_exposure_amount", float("inf"))

        order_value = context.quantity * context.current_price
        current_exposure = abs(context.current_position * context.current_price)
        expected_exposure = current_exposure + order_value

        balance_limit = context.available_balance * max_exposure_percent
        exposure_limit = min(max_exposure_amount, balance_limit)

        if expected_exposure > exposure_limit > 0:
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.name,
                result=RuleResult.REJECT,
                action=RuleAction.NOTIFY,
                message=(
                    f"Total exposure would exceed limit: "
                    f"{expected_exposure:.2f} > {exposure_limit:.2f}"
                ),
                metadata={
                    "current_exposure": current_exposure,
                    "expected_exposure": expected_exposure,
                    "exposure_limit": exposure_limit,
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

        allowed_hours: str = self.config.get("allowed_hours", "09:00-15:30")
        timezone_str: str = self.config.get("timezone", "Asia/Seoul")

        # 테스트 주입 또는 실제 시각
        now = context.metadata.get("current_time")
        if now is None:
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)

        current_time = now.time() if isinstance(now, datetime) else now

        start_str, end_str = allowed_hours.split("-")
        start_time = time.fromisoformat(start_str.strip())
        end_time = time.fromisoformat(end_str.strip())

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
