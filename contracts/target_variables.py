"""Frozen registry of target-variable string constants.

Part of the contracts/v1 API. Every desk that emits a Forecast must use one
of the constants below; the bus validator rejects any Forecast or Print whose
target_variable is not a member of KNOWN_TARGETS.

Additions are v1.x revisions to the spec (see docs/architecture_spec_v1.md
§0 change log, §4.6). Removals are breaking changes requiring a v2 bump.

The registry is domain-inclusive by design: oil target names and equity-VRP
target names coexist here. The portability target (§1.1, §8.4) exercises
this property under equity-VRP redeployment.

Rationale: eliminates the silent-failure mode where a typo in a desk's
target_variable produces a new unique string that no Print will ever match,
causing the Forecast to persist but never be graded.
"""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Phase 1 domain instance: crude oil (WTI/Brent)
# -----------------------------------------------------------------------------

# Storage & Curve desk (desk 3) — populated as the desk comes online.
# First registered target; all others added as desks are deepened per §12.1.
WTI_FRONT_MONTH_CLOSE = "wti_front_month_close"


# -----------------------------------------------------------------------------
# Phase 2 domain instance: equity VRP (Speckle and Spot)
# -----------------------------------------------------------------------------
# Populated at Phase 2 MVP per spec v1.12 (§14.7 synthetic-only month-5
# checkpoint). The portability test asserts these constants only appear
# here — shared-infra stays domain-neutral.

VIX_30D_FORWARD = "vix_30d_forward"
SPX_30D_IMPLIED_VOL = "spx_30d_implied_vol"


# -----------------------------------------------------------------------------
# Frozen set of all known targets
# -----------------------------------------------------------------------------

KNOWN_TARGETS: frozenset[str] = frozenset(
    {
        WTI_FRONT_MONTH_CLOSE,
        VIX_30D_FORWARD,
        SPX_30D_IMPLIED_VOL,
    }
)


def is_known(target_variable: str) -> bool:
    """Used by the bus validator on publish.

    Returns True iff target_variable is a registered constant. Prefer this
    over direct `in` tests so the call site is explicit about the contract
    it is enforcing.
    """
    return target_variable in KNOWN_TARGETS
