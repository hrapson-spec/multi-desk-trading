"""Synthetic queue, hidden-liquidity, and profitability diagnostics for S4."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from v2.s4_0.mbp10_fill import FillSide


class QueueEventKind(StrEnum):
    TRADE = "trade"
    CANCEL = "cancel"
    ADD = "add"


@dataclass(frozen=True)
class QueueEvent:
    kind: QueueEventKind
    quantity: float


@dataclass(frozen=True)
class QueuePositionScenario:
    order_id: str
    symbol: str
    side: FillSide
    order_quantity: float
    initial_queue_ahead: float
    events: tuple[QueueEvent, ...]


@dataclass(frozen=True)
class QueuePositionResult:
    order_id: str
    symbol: str
    side: FillSide
    order_quantity: float
    initial_queue_ahead: float
    final_queue_ahead: float
    queue_ahead_depleted_by_trades: float
    queue_ahead_depleted_by_cancels: float
    filled_quantity: float
    residual_quantity: float
    fill_ratio: float
    events_processed: int
    synthetic_queue_position_claimed: bool
    real_queue_position_claimed: bool
    errors: tuple[str, ...]
    result_hash: str

    @property
    def ok(self) -> bool:
        return not self.errors and self.synthetic_queue_position_claimed

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_quantity": self.order_quantity,
            "initial_queue_ahead": self.initial_queue_ahead,
            "final_queue_ahead": self.final_queue_ahead,
            "queue_ahead_depleted_by_trades": self.queue_ahead_depleted_by_trades,
            "queue_ahead_depleted_by_cancels": self.queue_ahead_depleted_by_cancels,
            "filled_quantity": self.filled_quantity,
            "residual_quantity": self.residual_quantity,
            "fill_ratio": self.fill_ratio,
            "events_processed": self.events_processed,
            "synthetic_queue_position_claimed": self.synthetic_queue_position_claimed,
            "real_queue_position_claimed": self.real_queue_position_claimed,
            "errors": list(self.errors),
            "ok": self.ok,
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True)
class HiddenLiquidityScenario:
    order_id: str
    symbol: str
    side: FillSide
    order_quantity: float
    displayed_quantity: float
    hidden_quantity: float
    replenish_clip: float | None = None


@dataclass(frozen=True)
class HiddenLiquidityResult:
    order_id: str
    symbol: str
    side: FillSide
    order_quantity: float
    displayed_quantity: float
    hidden_quantity: float
    visible_fill_quantity: float
    hidden_fill_quantity: float
    residual_quantity: float
    displayed_replenishments: int
    hidden_liquidity_model_declared: bool
    real_hidden_liquidity_claimed: bool
    errors: tuple[str, ...]
    result_hash: str

    @property
    def total_fill_quantity(self) -> float:
        return self.visible_fill_quantity + self.hidden_fill_quantity

    @property
    def fill_ratio(self) -> float:
        if self.order_quantity == 0:
            return 0.0
        return self.total_fill_quantity / self.order_quantity

    @property
    def ok(self) -> bool:
        return not self.errors and self.hidden_liquidity_model_declared

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_quantity": self.order_quantity,
            "displayed_quantity": self.displayed_quantity,
            "hidden_quantity": self.hidden_quantity,
            "visible_fill_quantity": self.visible_fill_quantity,
            "hidden_fill_quantity": self.hidden_fill_quantity,
            "total_fill_quantity": self.total_fill_quantity,
            "residual_quantity": self.residual_quantity,
            "fill_ratio": self.fill_ratio,
            "displayed_replenishments": self.displayed_replenishments,
            "hidden_liquidity_model_declared": self.hidden_liquidity_model_declared,
            "real_hidden_liquidity_claimed": self.real_hidden_liquidity_claimed,
            "errors": list(self.errors),
            "ok": self.ok,
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True)
class ProfitabilityTrade:
    trade_id: str
    side: FillSide
    quantity: float
    entry_price: float
    exit_price: float
    fees: float = 0.0


@dataclass(frozen=True)
class ProfitabilityDiagnostics:
    trades_total: int
    winning_trades: int
    losing_trades: int
    gross_pnl: float
    fees: float
    net_pnl: float
    average_trade_pnl: float | None
    hit_rate: float | None
    max_drawdown: float
    synthetic_profitability_claimed: bool
    real_profitability_claimed: bool
    errors: tuple[str, ...]
    result_hash: str

    @property
    def ok(self) -> bool:
        return not self.errors and self.synthetic_profitability_claimed

    def as_dict(self) -> dict[str, Any]:
        return {
            "trades_total": self.trades_total,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_pnl": self.gross_pnl,
            "fees": self.fees,
            "net_pnl": self.net_pnl,
            "average_trade_pnl": self.average_trade_pnl,
            "hit_rate": self.hit_rate,
            "max_drawdown": self.max_drawdown,
            "synthetic_profitability_claimed": self.synthetic_profitability_claimed,
            "real_profitability_claimed": self.real_profitability_claimed,
            "errors": list(self.errors),
            "ok": self.ok,
            "result_hash": self.result_hash,
        }


def simulate_queue_position(scenario: QueuePositionScenario) -> QueuePositionResult:
    errors = _validate_positive(
        ("order_quantity", scenario.order_quantity),
        ("initial_queue_ahead", scenario.initial_queue_ahead),
        allow_zero={"initial_queue_ahead"},
    )
    queue_ahead = max(scenario.initial_queue_ahead, 0.0)
    remaining = max(scenario.order_quantity, 0.0)
    depleted_by_trades = 0.0
    depleted_by_cancels = 0.0
    filled = 0.0
    processed = 0

    for event in scenario.events:
        processed += 1
        if event.quantity < 0:
            errors.append(f"{event.kind.value} event quantity must be >= 0")
            continue
        if remaining == 0:
            continue
        if event.kind == QueueEventKind.ADD:
            continue
        if queue_ahead > 0:
            depletion = min(queue_ahead, event.quantity)
            queue_ahead -= depletion
            if event.kind == QueueEventKind.TRADE:
                depleted_by_trades += depletion
                remaining_event_qty = event.quantity - depletion
                fill = min(remaining, remaining_event_qty)
                filled += fill
                remaining -= fill
            else:
                depleted_by_cancels += depletion
            continue
        if event.kind == QueueEventKind.TRADE:
            fill = min(remaining, event.quantity)
            filled += fill
            remaining -= fill

    payload = {
        "scenario": _queue_scenario_payload(scenario),
        "queue_ahead": queue_ahead,
        "depleted_by_trades": depleted_by_trades,
        "depleted_by_cancels": depleted_by_cancels,
        "filled": filled,
        "remaining": remaining,
        "errors": errors,
    }
    return QueuePositionResult(
        order_id=scenario.order_id,
        symbol=scenario.symbol,
        side=scenario.side,
        order_quantity=scenario.order_quantity,
        initial_queue_ahead=scenario.initial_queue_ahead,
        final_queue_ahead=queue_ahead,
        queue_ahead_depleted_by_trades=depleted_by_trades,
        queue_ahead_depleted_by_cancels=depleted_by_cancels,
        filled_quantity=filled,
        residual_quantity=remaining,
        fill_ratio=0.0 if scenario.order_quantity == 0 else filled / scenario.order_quantity,
        events_processed=processed,
        synthetic_queue_position_claimed=True,
        real_queue_position_claimed=False,
        errors=tuple(errors),
        result_hash=_sha256_json(payload),
    )


def simulate_hidden_liquidity(
    scenario: HiddenLiquidityScenario,
) -> HiddenLiquidityResult:
    errors = _validate_positive(
        ("order_quantity", scenario.order_quantity),
        ("displayed_quantity", scenario.displayed_quantity),
        ("hidden_quantity", scenario.hidden_quantity),
        allow_zero={"displayed_quantity", "hidden_quantity"},
    )
    if scenario.replenish_clip is not None and scenario.replenish_clip <= 0:
        errors.append("replenish_clip must be > 0 when provided")

    remaining = max(scenario.order_quantity, 0.0)
    visible_fill = min(remaining, max(scenario.displayed_quantity, 0.0))
    remaining -= visible_fill
    hidden_available = max(scenario.hidden_quantity, 0.0)
    hidden_fill = min(remaining, hidden_available)
    remaining -= hidden_fill
    replenishments = _replenishment_count(hidden_fill, scenario.replenish_clip)

    payload = {
        "scenario": _hidden_scenario_payload(scenario),
        "visible_fill": visible_fill,
        "hidden_fill": hidden_fill,
        "remaining": remaining,
        "replenishments": replenishments,
        "errors": errors,
    }
    return HiddenLiquidityResult(
        order_id=scenario.order_id,
        symbol=scenario.symbol,
        side=scenario.side,
        order_quantity=scenario.order_quantity,
        displayed_quantity=scenario.displayed_quantity,
        hidden_quantity=scenario.hidden_quantity,
        visible_fill_quantity=visible_fill,
        hidden_fill_quantity=hidden_fill,
        residual_quantity=remaining,
        displayed_replenishments=replenishments,
        hidden_liquidity_model_declared=True,
        real_hidden_liquidity_claimed=False,
        errors=tuple(errors),
        result_hash=_sha256_json(payload),
    )


def evaluate_profitability(
    trades: list[ProfitabilityTrade],
) -> ProfitabilityDiagnostics:
    errors: list[str] = []
    pnls: list[float] = []
    total_fees = 0.0
    for trade in trades:
        if trade.quantity <= 0:
            errors.append(f"{trade.trade_id}: quantity must be > 0")
        if trade.entry_price <= 0 or trade.exit_price <= 0:
            errors.append(f"{trade.trade_id}: prices must be > 0")
        if trade.fees < 0:
            errors.append(f"{trade.trade_id}: fees must be >= 0")
        gross = _gross_pnl(trade)
        total_fees += trade.fees
        pnls.append(gross - trade.fees)

    gross_pnl = sum(_gross_pnl(trade) for trade in trades)
    net_pnl = sum(pnls)
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)
    payload = {
        "trades": [_trade_payload(trade) for trade in trades],
        "pnls": pnls,
        "errors": errors,
    }
    return ProfitabilityDiagnostics(
        trades_total=len(trades),
        winning_trades=wins,
        losing_trades=losses,
        gross_pnl=gross_pnl,
        fees=total_fees,
        net_pnl=net_pnl,
        average_trade_pnl=None if not pnls else net_pnl / len(pnls),
        hit_rate=None if not pnls else wins / len(pnls),
        max_drawdown=_max_drawdown(pnls),
        synthetic_profitability_claimed=True,
        real_profitability_claimed=False,
        errors=tuple(errors),
        result_hash=_sha256_json(payload),
    )


def _validate_positive(
    *items: tuple[str, float],
    allow_zero: set[str] | None = None,
) -> list[str]:
    allow_zero = allow_zero or set()
    errors: list[str] = []
    for name, value in items:
        if name in allow_zero:
            if value < 0:
                errors.append(f"{name} must be >= 0")
        elif value <= 0:
            errors.append(f"{name} must be > 0")
    return errors


def _replenishment_count(hidden_fill: float, replenish_clip: float | None) -> int:
    if hidden_fill == 0 or replenish_clip is None or replenish_clip <= 0:
        return 0
    full, remainder = divmod(hidden_fill, replenish_clip)
    return int(full + (1 if remainder else 0))


def _gross_pnl(trade: ProfitabilityTrade) -> float:
    if trade.side == FillSide.BUY:
        return (trade.exit_price - trade.entry_price) * trade.quantity
    return (trade.entry_price - trade.exit_price) * trade.quantity


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _queue_scenario_payload(scenario: QueuePositionScenario) -> dict[str, Any]:
    return {
        "order_id": scenario.order_id,
        "symbol": scenario.symbol,
        "side": scenario.side.value,
        "order_quantity": scenario.order_quantity,
        "initial_queue_ahead": scenario.initial_queue_ahead,
        "events": [
            {"kind": event.kind.value, "quantity": event.quantity}
            for event in scenario.events
        ],
    }


def _hidden_scenario_payload(scenario: HiddenLiquidityScenario) -> dict[str, Any]:
    return {
        "order_id": scenario.order_id,
        "symbol": scenario.symbol,
        "side": scenario.side.value,
        "order_quantity": scenario.order_quantity,
        "displayed_quantity": scenario.displayed_quantity,
        "hidden_quantity": scenario.hidden_quantity,
        "replenish_clip": scenario.replenish_clip,
    }


def _trade_payload(trade: ProfitabilityTrade) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_id,
        "side": trade.side.value,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "fees": trade.fees,
    }


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
