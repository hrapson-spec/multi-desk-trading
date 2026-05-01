"""Synthetic claim diagnostics for queue, hidden-liquidity, and PnL mechanics."""

from __future__ import annotations

import pytest

from v2.s4_0.mbp10_fill import FillSide
from v2.s4_0.synthetic_claims import (
    HiddenLiquidityScenario,
    ProfitabilityTrade,
    QueueEvent,
    QueueEventKind,
    QueuePositionScenario,
    evaluate_profitability,
    simulate_hidden_liquidity,
    simulate_queue_position,
)


def test_queue_position_diagnostic_tracks_synthetic_queue_math_without_real_claim():
    scenario = QueuePositionScenario(
        order_id="queue_probe",
        symbol="CLM6",
        side=FillSide.BUY,
        order_quantity=20,
        initial_queue_ahead=15,
        events=(
            QueueEvent(QueueEventKind.TRADE, 5),
            QueueEvent(QueueEventKind.CANCEL, 4),
            QueueEvent(QueueEventKind.TRADE, 10),
            QueueEvent(QueueEventKind.TRADE, 16),
        ),
    )

    result = simulate_queue_position(scenario)

    assert result.ok is True
    assert result.final_queue_ahead == 0
    assert result.queue_ahead_depleted_by_trades == 11
    assert result.queue_ahead_depleted_by_cancels == 4
    assert result.filled_quantity == 20
    assert result.residual_quantity == 0
    assert result.fill_ratio == 1
    assert result.events_processed == 4
    assert result.synthetic_queue_position_claimed is True
    assert result.real_queue_position_claimed is False
    assert result.errors == ()
    assert result.as_dict()["result_hash"] == result.result_hash


def test_queue_position_diagnostic_is_deterministic_for_same_scenario():
    scenario = QueuePositionScenario(
        order_id="queue_deterministic",
        symbol="CLN6",
        side=FillSide.SELL,
        order_quantity=7,
        initial_queue_ahead=3,
        events=(
            QueueEvent(QueueEventKind.ADD, 100),
            QueueEvent(QueueEventKind.CANCEL, 1),
            QueueEvent(QueueEventKind.TRADE, 10),
        ),
    )

    first = simulate_queue_position(scenario)
    second = simulate_queue_position(scenario)

    assert first.result_hash == second.result_hash
    assert first.as_dict() == second.as_dict()


def test_queue_position_diagnostic_reports_bad_event_quantity():
    result = simulate_queue_position(
        QueuePositionScenario(
            order_id="queue_bad_event",
            symbol="CLM6",
            side=FillSide.BUY,
            order_quantity=5,
            initial_queue_ahead=0,
            events=(QueueEvent(QueueEventKind.TRADE, -1),),
        )
    )

    assert result.ok is False
    assert result.errors == ("trade event quantity must be >= 0",)
    assert result.real_queue_position_claimed is False


def test_hidden_liquidity_diagnostic_separates_modelled_hidden_size_from_real_claim():
    scenario = HiddenLiquidityScenario(
        order_id="hidden_probe",
        symbol="CLM6",
        side=FillSide.BUY,
        order_quantity=30,
        displayed_quantity=10,
        hidden_quantity=15,
        replenish_clip=5,
    )

    result = simulate_hidden_liquidity(scenario)

    assert result.ok is True
    assert result.visible_fill_quantity == 10
    assert result.hidden_fill_quantity == 15
    assert result.total_fill_quantity == 25
    assert result.residual_quantity == 5
    assert result.fill_ratio == pytest.approx(25 / 30)
    assert result.displayed_replenishments == 3
    assert result.hidden_liquidity_model_declared is True
    assert result.real_hidden_liquidity_claimed is False
    assert result.errors == ()
    assert result.as_dict()["result_hash"] == result.result_hash


def test_hidden_liquidity_diagnostic_reports_invalid_replenishment_clip():
    result = simulate_hidden_liquidity(
        HiddenLiquidityScenario(
            order_id="hidden_bad_clip",
            symbol="CLM6",
            side=FillSide.SELL,
            order_quantity=1,
            displayed_quantity=0,
            hidden_quantity=1,
            replenish_clip=0,
        )
    )

    assert result.ok is False
    assert result.errors == ("replenish_clip must be > 0 when provided",)
    assert result.real_hidden_liquidity_claimed is False


def test_profitability_diagnostic_reports_synthetic_pnl_without_real_claim():
    result = evaluate_profitability(
        [
            ProfitabilityTrade(
                "buy_win",
                FillSide.BUY,
                quantity=10,
                entry_price=75,
                exit_price=76,
                fees=1,
            ),
            ProfitabilityTrade(
                "sell_win",
                FillSide.SELL,
                quantity=5,
                entry_price=80,
                exit_price=78,
                fees=0.5,
            ),
            ProfitabilityTrade(
                "buy_loss",
                FillSide.BUY,
                quantity=4,
                entry_price=50,
                exit_price=49,
                fees=0.25,
            ),
        ]
    )

    assert result.ok is True
    assert result.trades_total == 3
    assert result.winning_trades == 2
    assert result.losing_trades == 1
    assert result.gross_pnl == 16
    assert result.fees == 1.75
    assert result.net_pnl == 14.25
    assert result.average_trade_pnl == 4.75
    assert result.hit_rate == pytest.approx(2 / 3)
    assert result.max_drawdown == 4.25
    assert result.synthetic_profitability_claimed is True
    assert result.real_profitability_claimed is False
    assert result.errors == ()
    assert result.as_dict()["result_hash"] == result.result_hash


def test_profitability_diagnostic_is_deterministic_for_same_trades():
    trades = [
        ProfitabilityTrade(
            "round_trip",
            FillSide.BUY,
            quantity=2,
            entry_price=70,
            exit_price=71,
            fees=0.1,
        )
    ]

    first = evaluate_profitability(trades)
    second = evaluate_profitability(trades)

    assert first.result_hash == second.result_hash
    assert first.as_dict() == second.as_dict()


def test_profitability_diagnostic_reports_invalid_trade_inputs():
    result = evaluate_profitability(
        [
            ProfitabilityTrade(
                "bad_trade",
                FillSide.BUY,
                quantity=0,
                entry_price=0,
                exit_price=70,
                fees=-1,
            )
        ]
    )

    assert result.ok is False
    assert result.errors == (
        "bad_trade: quantity must be > 0",
        "bad_trade: prices must be > 0",
        "bad_trade: fees must be >= 0",
    )
    assert result.real_profitability_claimed is False
