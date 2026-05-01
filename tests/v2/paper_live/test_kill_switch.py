"""Kill-switch reader and loop behavior tests."""

from __future__ import annotations

from datetime import timedelta

from v2.contracts import DegradationState
from v2.execution import AdapterParams, ControlLawParams
from v2.execution.simulator import InternalSimulator
from v2.paper_live import PaperLiveLoop
from v2.runtime.kill_switch import load_kill_switch

from .helpers import (
    CODE_COMMIT,
    CONTRACT_HASH,
    FAMILY,
    PREREG_HASH,
    RELEASE_CALENDAR_VERSION,
    dt,
    make_forecast,
)


class _Desk:
    family_id = FAMILY

    def __init__(self, desk_id: str):
        self.desk_id = desk_id
        self.calls = 0

    def feature_specs(self):
        return []

    def forecast(
        self,
        view,
        *,
        prereg_hash,
        code_commit,
        contract_hash="",
        release_calendar_version="",
        emitted_ts=None,
    ):
        self.calls += 1
        return make_forecast(
            view.as_of_ts,
            desk_id=self.desk_id,
            emitted_ts=emitted_ts,
        )


def test_missing_kill_switch_defaults_enabled(tmp_path):
    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.effective_state(FAMILY) == "enabled"
    assert state.is_halting(FAMILY) is False
    assert state.isolated_desks(FAMILY) == ()


def test_kill_switch_reads_isolated_desks(tmp_path):
    (tmp_path / "kill_switch.yaml").write_text(
        """
system_state: enabled
families:
  oil_wti_5d:
    state: enabled
    isolated_desks: [desk_a]
    reason: bad inputs
""",
        encoding="utf-8",
    )
    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.is_halting(FAMILY) is False
    assert state.isolated_desks(FAMILY) == ("desk_a",)
    assert state.reason(FAMILY) == "bad inputs"


def test_loop_halting_kill_switch_skips_desks_and_persists_force_flat(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "kill_switch.yaml").write_text(
        """
system_state: halted
reason: operator stop
families:
  oil_wti_5d:
    state: enabled
    isolated_desks: []
""",
        encoding="utf-8",
    )
    desk = _Desk("desk_a")
    sim = InternalSimulator.open(runtime_root)
    loop = _loop(tmp_path / "pit", sim, [desk])
    try:
        outcome = loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )
        assert desk.calls == 0
        assert outcome.decision.abstain_reason == "kill_switch:operator stop"
        assert outcome.new_exposure.state == DegradationState.HARD_FAIL
        assert sim.counts() == {"family_decisions": 1, "execution_ledger": 2}
    finally:
        loop.close()
        sim.close()


def test_loop_skips_isolated_desk_but_calls_remaining_desks(tmp_path):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / "kill_switch.yaml").write_text(
        """
system_state: enabled
families:
  oil_wti_5d:
    state: enabled
    isolated_desks: [desk_a]
""",
        encoding="utf-8",
    )
    desk_a = _Desk("desk_a")
    desk_b = _Desk("desk_b")
    sim = InternalSimulator.open(runtime_root)
    loop = _loop(tmp_path / "pit", sim, [desk_a, desk_b])
    try:
        outcome = loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )
        assert desk_a.calls == 0
        assert desk_b.calls == 1
        assert outcome.decision.abstain is False
    finally:
        loop.close()
        sim.close()


def _loop(pit_root, simulator, desks):
    return PaperLiveLoop(
        pit_root=pit_root,
        family=FAMILY,
        desks=desks,
        simulator=simulator,
        control_params=ControlLawParams(k=1.0),
        adapter_params=AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1_000.0,
        ),
        n_soft=2,
        decay_lambda=0.25,
        ttl=timedelta(days=1),
        contract_hash=CONTRACT_HASH,
        release_calendar_version=RELEASE_CALENDAR_VERSION,
        prereg_hash=PREREG_HASH,
        code_commit=CODE_COMMIT,
    )
