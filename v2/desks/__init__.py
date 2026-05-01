"""v2 desks.

Roadmap (per docs/v2/model_inventory.md):
    v2.0: oil/prompt_balance_nowcast (scaffold → real)
    v2.1: oil/disruption_event
    v2.2: oil/cross_asset_transmission + regime_classifier activation
    v2.3: equity_vrp/surface_state
    v2.4: equity_vrp/scheduled_catalyst
"""

from v2.desks.base import DeskV2

__all__ = ["DeskV2"]
