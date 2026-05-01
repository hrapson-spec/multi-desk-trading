"""Merged oil demand-nowcast desk (v1.16 restructure).

Absorbs the pre-v1.16 `demand` desk plus the alpha portion of `macro`. Macro
residual is demoted to regime-conditioning state via `regime_classifier`.
Mixed-frequency nowcast framing; emits `WTI_FRONT_1W_LOG_RETURN`.
"""

from __future__ import annotations

from .classical import ClassicalOilDemandNowcastModel
from .desk import OilDemandNowcastDesk

__all__ = ["ClassicalOilDemandNowcastModel", "OilDemandNowcastDesk"]
