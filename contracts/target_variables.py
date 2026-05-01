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
WTI_FRONT_1W_LOG_RETURN = "wti_front_1w_log_return"
WTI_FRONT_1D_RETURN_SIGN = "wti_front_1d_return_sign"

# v1.x addition (data plan Tier 3.A) — 3-day horizon variants admitted
# under feasibility/reports/n_requirement_spec_v1.md §13. Backed by the
# dependence analysis at docs/v2/dependence_analysis_3d_horizon.md.
# Magnitude variant is intentionally NOT registered: its HAC effective N
# (133) falls below the Phase 3 floor of 250 due to volatility
# clustering (see spec v1 §13.1).
WTI_FRONT_3D_LOG_RETURN = "wti_front_3d_log_return"
WTI_FRONT_3D_RETURN_SIGN = "wti_front_3d_return_sign"

# v1.x addition (data plan Tier 3.B) — multi-asset target streams.
# Per spec §11 forbidden #4 ("Borrowing N across targets"), each asset
# is its own per-target N stream. Phase 0 source for prices is
# stooq.com EOD redistribution (free-rehearsal only); see
# data/s4_0/free_source/licence_clearance/owner_clearance_decision.md.
BRENT_FRONT_5D_LOG_RETURN = "brent_front_5d_log_return"
RBOB_FRONT_5D_LOG_RETURN = "rbob_front_5d_log_return"
NG_FRONT_5D_LOG_RETURN = "ng_front_5d_log_return"


# -----------------------------------------------------------------------------
# Phase 2 domain instance: equity VRP (Speckle and Spot)
# -----------------------------------------------------------------------------
# Populated at Phase 2 MVP per spec v1.12 (§14.7 synthetic-only month-5
# checkpoint). The portability test asserts these constants only appear
# here — shared-infra stays domain-neutral.

VIX_30D_FORWARD = "vix_30d_forward"
SPX_30D_IMPLIED_VOL = "spx_30d_implied_vol"
# v1.16 addition: signed 3-day delta. Shared decision-space unit for the equity
# family so controller/decision.py:94-112 can raw-sum across equity desks.
VIX_30D_FORWARD_3D_DELTA = "vix_30d_forward_3d_delta"


# -----------------------------------------------------------------------------
# Frozen set of all known targets
# -----------------------------------------------------------------------------

KNOWN_TARGETS: frozenset[str] = frozenset(
    {
        WTI_FRONT_MONTH_CLOSE,
        WTI_FRONT_1W_LOG_RETURN,
        WTI_FRONT_1D_RETURN_SIGN,
        WTI_FRONT_3D_LOG_RETURN,
        WTI_FRONT_3D_RETURN_SIGN,
        BRENT_FRONT_5D_LOG_RETURN,
        RBOB_FRONT_5D_LOG_RETURN,
        NG_FRONT_5D_LOG_RETURN,
        VIX_30D_FORWARD,
        SPX_30D_IMPLIED_VOL,
        VIX_30D_FORWARD_3D_DELTA,
    }
)


def is_known(target_variable: str) -> bool:
    """Used by the bus validator on publish.

    Returns True iff target_variable is a registered constant. Prefer this
    over direct `in` tests so the call site is explicit about the contract
    it is enforcing.
    """
    return target_variable in KNOWN_TARGETS
