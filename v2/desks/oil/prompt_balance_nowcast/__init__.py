"""prompt_balance_nowcast desk (v2.0 first desk).

Mechanism memo: spec.md.
Implementation: desk.py (currently a scaffold emitting the B0 baseline;
replaced by the dynamic-factor nowcast at S1→S2 promotion).
"""

from v2.desks.oil.prompt_balance_nowcast.desk import PromptBalanceNowcastDesk

__all__ = ["PromptBalanceNowcastDesk"]
