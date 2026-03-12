"""전략별 룰 — 특정 봇/전략에만 적용되는 룰."""

from __future__ import annotations

from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult


class PositionSizeRule(Rule):
    """포지션 사이즈 제한."""

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        max_position_percent = self.config.get("max_position_percent", 0.10)
        max_position_amount = self.config.get("max_position_amount", float("inf"))

        current_position_value = abs(context.current_position * context.current_price)
        order_value = context.quantity * context.current_price
        total_position_value = current_position_value + order_value

        balance_limit = context.available_balance * max_position_percent
        position_limit = min(max_position_amount, balance_limit)

        if total_position_value > position_limit > 0:
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.name,
                result=RuleResult.REJECT,
                action=RuleAction.NOTIFY,
                message=(
                    f"Position size would exceed limit: "
                    f"{total_position_value:.2f} > {position_limit:.2f}"
                ),
                metadata={
                    "current_position_value": current_position_value,
                    "order_value": order_value,
                    "total_position_value": total_position_value,
                    "position_limit": position_limit,
                },
            )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Position size within limits",
        )


class UnrealizedLossLimitRule(Rule):
    """봇의 미실현 손실이 한도를 초과하면 추가 매수 차단.

    매도는 허용하여 포지션 정리가 가능하도록 한다.
    context.metadata에서 unrealized_pnl, allocated_budget을 참조.
    """

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        max_loss_pct = self.config.get("max_unrealized_loss_percent", 0.10)

        unrealized_pnl = context.metadata.get("unrealized_pnl", 0.0)
        allocated_budget = context.metadata.get("allocated_budget", 0.0)

        if allocated_budget > 0 and unrealized_pnl < 0 and context.side == "buy":
            loss_pct = abs(unrealized_pnl) / allocated_budget
            if loss_pct > max_loss_pct:
                return RuleEvaluation(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    result=RuleResult.REJECT,
                    action=RuleAction.NOTIFY,
                    message=(
                        f"Unrealized loss {loss_pct:.1%} "
                        f"exceeds limit {max_loss_pct:.1%}"
                    ),
                    metadata={
                        "unrealized_pnl": unrealized_pnl,
                        "loss_percent": loss_pct,
                        "limit_percent": max_loss_pct,
                    },
                )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Unrealized loss within limits",
        )


class TradeFrequencyRule(Rule):
    """단위 시간당 거래 빈도 제한.

    context.metadata["recent_trade_count"]에서 최근 거래 수를 참조.
    """

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        max_trades = self.config.get("max_trades_per_hour", 10)

        recent_trades = context.metadata.get("recent_trade_count", 0)

        if recent_trades >= max_trades:
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.name,
                result=RuleResult.REJECT,
                action=RuleAction.LOG,
                message=(
                    f"Trade frequency limit exceeded: {recent_trades} >= {max_trades}"
                ),
                metadata={
                    "recent_trades": recent_trades,
                    "max_trades_per_hour": max_trades,
                },
            )

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="Trade frequency within limits",
        )
