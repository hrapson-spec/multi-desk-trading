"""Shared helpers for classical specialists (§5, plan §A).

The 5 desk-specific ridge/OLS models live in their own `desks/*/classical.py`
modules, but share the same closed-form ridge solve and the same pattern
for converting a per-desk log-return prediction into a price Forecast via
the market reference price. Keeping this utility shared avoids duplicating
the linear-algebra boilerplate.
"""

from __future__ import annotations

from .ridge import fit_ridge, predict_ridge

__all__ = ["fit_ridge", "predict_ridge"]
