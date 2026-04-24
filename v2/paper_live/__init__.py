"""Paper-live loop.

Daily EOD decision tick that composes:
    PIT store read → FeatureView → Desk forecast → Synthesiser →
    Control law → Degradation step → Adapter → Internal simulator fill.

The tick is implemented as a pure function `run_decision_tick(context)`
returning a `TickOutcome`. A thin driver wraps it with persistence and
scheduling. The driver is separate so the tick logic is unit-testable
without a running daemon.
"""

from v2.paper_live.loop import (
    MarketTickContext,
    PaperLiveLoop,
    TickOutcome,
    run_decision_tick,
)

__all__ = [
    "MarketTickContext",
    "PaperLiveLoop",
    "TickOutcome",
    "run_decision_tick",
]
