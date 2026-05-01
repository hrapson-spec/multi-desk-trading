"""Family synthesiser.

Combines desk-level ForecastV2 objects into a single family-level
predictive distribution on the same fixed quantile grid. At v2.0 the
pool is trivially identity for a single desk; the code is written for
the multi-desk case so v2.1+ plugs in without a contract change.

Entry point:
    synthesise_family(forecasts, *, regime_posterior, family_id, ...)
        → FamilyForecast

Two distinct failure modes:
    - desk exclusion: one desk's effective weight falls to zero
      (calibration × data_quality × regime collapse) but other desks
      remain. The excluded desk is dropped and weights renormalise.
    - family abstention: any input forecast has `abstain=True`
      (hard-gate cascade per R9), OR no desks remain after exclusion.
"""

from v2.synthesiser.compat import FamilyInputMismatchError, assert_compatible
from v2.synthesiser.linear_pool import FamilyForecast, synthesise_family
from v2.synthesiser.pool import weighted_linear_pool_cdf

__all__ = [
    "FamilyForecast",
    "FamilyInputMismatchError",
    "assert_compatible",
    "synthesise_family",
    "weighted_linear_pool_cdf",
]
