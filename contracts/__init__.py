"""Public API of the contracts/v1 module.

Import pattern for desks:
    from contracts.v1 import Forecast, Print, DirectionalClaim, ...
    from contracts.target_variables import KNOWN_TARGETS, WTI_FRONT_MONTH_CLOSE

Import pattern for the bus, Controller, grading harness:
    from contracts import v1, target_variables

See docs/architecture_spec_v1.md §4 for the authoritative spec.
"""

from __future__ import annotations

from . import target_variables, v1

__all__ = ["v1", "target_variables"]
