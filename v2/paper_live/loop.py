"""B6b paper-live decision tick orchestration.

`run_decision_tick` is pure: all timing, forecasts, prior exposure, and
runtime controls are explicit inputs. `PaperLiveLoop` is the stateful
driver that reads the kill-switch, builds FeatureViews, calls desks,
persists the decision and execution rows, and updates in-memory exposure
for the next tick.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from v2.contracts.decision_v2 import DecisionV2, DegradationState
from v2.contracts.forecast_v2 import ForecastV2
from v2.contracts.target_variables import lookup_target
from v2.desks.base import DeskV2
from v2.eval.cost_model import CostParams, CostScenario, apply_costs
from v2.execution.adapter import AdapterParams, target_lots
from v2.execution.control_law import ControlLawParams, compute_target_risk_budget
from v2.execution.degradation import ExposureState, TickEvent, step
from v2.execution.simulator import InternalSimulator, LedgerRecord, content_hash
from v2.feature_view.builder import build_feature_view
from v2.pit_store.manifest import PITManifest
from v2.pit_store.reader import PITReader
from v2.runtime.kill_switch import HALTING_STATES, KillSwitchState, load_kill_switch
from v2.synthesiser import FamilyForecast, synthesise_family

_DEFAULT_TARGET_VARIABLE = "WTI_FRONT_1W_LOG_RETURN"
_DEFAULT_ROLL_RULE_ID = "rolling_rule_v1"
_Z_90_05_WIDTH = 3.289707253902945


@dataclass(frozen=True)
class MarketTickContext:
    """Snapshot of inputs needed at a single tick."""

    decision_ts: datetime
    emitted_ts: datetime
    family: str
    forecasts: list[ForecastV2]
    price: float
    realised_return_since_last_tick: float
    market_vol_5d: float
    prior_exposure: ExposureState
    kill_switch_state: str
    contract_hash: str
    release_calendar_version: str
    prereg_hash: str
    prior_lots: int = 0
    regime_posterior: dict[str, float] | None = None
    override_abstain_reason: str | None = None
    kill_switch_halting: bool = False
    target_variable: str = _DEFAULT_TARGET_VARIABLE
    roll_rule_id: str = _DEFAULT_ROLL_RULE_ID


@dataclass(frozen=True)
class TickOutcome:
    decision: DecisionV2
    family_forecast: FamilyForecast
    b_t: float | None
    new_exposure: ExposureState
    target_lots: int
    raw_lots: float
    effective_b: float
    forecast_ids: tuple[str, ...]
    ledger_records: tuple[LedgerRecord, ...]


def run_decision_tick(
    context: MarketTickContext,
    *,
    control_params: ControlLawParams,
    adapter_params: AdapterParams,
    n_soft: int,
    decay_lambda: float,
    ttl: timedelta,
    optimistic_costs: CostParams | None = None,
    pessimistic_costs: CostParams | None = None,
) -> TickOutcome:
    """Pure orchestration of one paper-live decision tick."""
    _require_utc(context.decision_ts, "decision_ts")
    _require_utc(context.emitted_ts, "emitted_ts")

    optimistic_costs = optimistic_costs or CostParams.optimistic_default()
    pessimistic_costs = pessimistic_costs or CostParams.pessimistic_default()

    family_forecast = _family_forecast_for_context(context)
    forecast_ids = tuple(forecast.forecast_id for forecast in context.forecasts)

    raw_b_t = compute_target_risk_budget(family_forecast, params=control_params)
    ttl_breached = _ttl_breached(context, ttl)
    kill_halting = context.kill_switch_halting or context.kill_switch_state in HALTING_STATES

    ladder_b_t = None if ttl_breached else raw_b_t
    event = TickEvent(
        family_abstained=(ladder_b_t is None),
        b_t=ladder_b_t,
        ttl_breached=ttl_breached,
        kill_switch_halting=kill_halting,
    )
    new_exposure = step(
        context.prior_exposure, event, n_soft=n_soft, decay_lambda=decay_lambda
    )

    lot_result = target_lots(
        b_t=new_exposure.current_target,
        price=context.price,
        market_vol_5d=context.market_vol_5d,
        params=adapter_params,
    )

    decision = _build_decision(
        context=context,
        family_forecast=family_forecast,
        raw_b_t=raw_b_t,
        ttl_breached=ttl_breached,
        kill_halting=kill_halting,
        new_exposure=new_exposure,
        control_params=control_params,
        ttl=ttl,
        forecast_ids=forecast_ids,
    )

    opt_rep = _cost_report(context, new_exposure, optimistic_costs)
    pess_rep = _cost_report(context, new_exposure, pessimistic_costs)

    records = (
        _ledger_record(
            context=context,
            decision=decision,
            new_exposure=new_exposure,
            lot_result=lot_result,
            scenario=CostScenario.OPTIMISTIC,
            fill_cost=float(opt_rep.cost_total),
            gross_return=float(opt_rep.gross_return_total),
            net_return=float(opt_rep.net_return_total),
            forecast_ids=forecast_ids,
        ),
        _ledger_record(
            context=context,
            decision=decision,
            new_exposure=new_exposure,
            lot_result=lot_result,
            scenario=CostScenario.PESSIMISTIC,
            fill_cost=float(pess_rep.cost_total),
            gross_return=float(pess_rep.gross_return_total),
            net_return=float(pess_rep.net_return_total),
            forecast_ids=forecast_ids,
        ),
    )

    return TickOutcome(
        decision=decision,
        family_forecast=family_forecast,
        b_t=raw_b_t,
        new_exposure=new_exposure,
        target_lots=lot_result.rounded_lots,
        raw_lots=lot_result.raw_lots,
        effective_b=lot_result.effective_b,
        forecast_ids=forecast_ids,
        ledger_records=records,
    )


class PaperLiveLoop:
    """Stateful single-family paper-live driver."""

    def __init__(
        self,
        *,
        pit_root: Path,
        family: str,
        desks: list[DeskV2],
        simulator: InternalSimulator,
        control_params: ControlLawParams,
        adapter_params: AdapterParams,
        n_soft: int,
        decay_lambda: float,
        ttl: timedelta,
        contract_hash: str,
        release_calendar_version: str,
        prereg_hash: str,
        code_commit: str,
    ):
        self.pit_root = Path(pit_root)
        self.family = family
        self.desks = list(desks)
        self.simulator = simulator
        self.control_params = control_params
        self.adapter_params = adapter_params
        self.n_soft = n_soft
        self.decay_lambda = decay_lambda
        self.ttl = ttl
        self.contract_hash = contract_hash
        self.release_calendar_version = release_calendar_version
        self.prereg_hash = prereg_hash
        self.code_commit = code_commit

        self._manifest = PITManifest.open(self.pit_root)
        self._reader = PITReader(self.pit_root, self._manifest)
        self._exposure = ExposureState(
            state=DegradationState.HEALTHY,
            current_target=0.0,
            last_valid_target=0.0,
            ticks_since_valid=0,
        )
        latest_execution = self.simulator.latest(self.family, CostScenario.OPTIMISTIC)
        self._prior_lots = latest_execution.new_lots if latest_execution is not None else 0

    def tick(
        self,
        *,
        decision_ts: datetime,
        price: float,
        realised_return_since_last_tick: float,
        market_vol_5d: float,
        emitted_ts: datetime | None = None,
        regime_posterior: dict[str, float] | None = None,
    ) -> TickOutcome:
        emitted = emitted_ts if emitted_ts is not None else datetime.now(UTC)
        if emitted < decision_ts:
            emitted = decision_ts

        kill_switch = load_kill_switch(self.simulator.runtime_root, family=self.family)
        forecasts, override_reason = self._collect_forecasts(
            decision_ts=decision_ts,
            emitted_ts=emitted,
            kill_switch=kill_switch,
        )

        context = MarketTickContext(
            decision_ts=decision_ts,
            emitted_ts=emitted,
            family=self.family,
            forecasts=forecasts,
            price=price,
            realised_return_since_last_tick=realised_return_since_last_tick,
            market_vol_5d=market_vol_5d,
            prior_exposure=self._exposure,
            prior_lots=self._prior_lots,
            kill_switch_state=kill_switch.effective_state(self.family),
            kill_switch_halting=kill_switch.is_halting(self.family),
            override_abstain_reason=override_reason,
            contract_hash=self.contract_hash,
            release_calendar_version=self.release_calendar_version,
            prereg_hash=self.prereg_hash,
            regime_posterior=regime_posterior,
        )
        outcome = run_decision_tick(
            context,
            control_params=self.control_params,
            adapter_params=self.adapter_params,
            n_soft=self.n_soft,
            decay_lambda=self.decay_lambda,
            ttl=self.ttl,
        )

        decision_record = self.simulator.record_decision(
            decision=outcome.decision,
            family_forecast_hash=content_hash(outcome.family_forecast),
            forecast_ids=outcome.forecast_ids,
            kill_switch_state=kill_switch.as_dict(),
            emitted_ts=emitted,
        )
        execution_ids = tuple(
            self.simulator.record_tick(replace(record, decision_id=decision_record.decision_id))
            for record in outcome.ledger_records
        )
        self.simulator.write_snapshot_receipt(
            decision_ts=decision_ts,
            decision_id=decision_record.decision_id,
            execution_ids=execution_ids,
            kill_switch_hash=decision_record.kill_switch_hash,
            code_commit=self.code_commit,
            contract_hash=self.contract_hash,
            pit_manifest_hash=_source_manifest_hash(forecasts),
        )

        self._exposure = outcome.new_exposure
        self._prior_lots = outcome.target_lots
        return outcome

    def close(self) -> None:
        self._manifest.close()

    def __enter__(self) -> PaperLiveLoop:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _collect_forecasts(
        self,
        *,
        decision_ts: datetime,
        emitted_ts: datetime,
        kill_switch: KillSwitchState,
    ) -> tuple[list[ForecastV2], str | None]:
        if kill_switch.is_halting(self.family):
            return [], f"kill_switch:{kill_switch.reason(self.family)}"

        isolated = set(kill_switch.isolated_desks(self.family))
        active_desks = [desk for desk in self.desks if desk.desk_id not in isolated]
        if not active_desks:
            reason = "all desks isolated by kill_switch" if isolated else "no active desks"
            return [], reason

        forecasts: list[ForecastV2] = []
        for desk in active_desks:
            view = build_feature_view(
                as_of_ts=decision_ts,
                family=self.family,
                desk=desk.desk_id,
                specs=desk.feature_specs(),
                reader=self._reader,
            )
            forecasts.append(
                desk.forecast(
                    view,
                    prereg_hash=self.prereg_hash,
                    code_commit=self.code_commit,
                    contract_hash=self.contract_hash,
                    release_calendar_version=self.release_calendar_version,
                    emitted_ts=emitted_ts,
                )
            )
        return forecasts, None


# -- pure helpers ------------------------------------------------------------


def _family_forecast_for_context(context: MarketTickContext) -> FamilyForecast:
    if context.override_abstain_reason is not None or not context.forecasts:
        reason = context.override_abstain_reason or "no desks contributed"
        return _synthetic_family_abstain(context, reason=reason)
    return synthesise_family(
        context.forecasts,
        regime_posterior=context.regime_posterior,
        contract_hash=context.contract_hash,
        release_calendar_version=context.release_calendar_version,
    )


def _synthetic_family_abstain(context: MarketTickContext, *, reason: str) -> FamilyForecast:
    target_variable = (
        context.forecasts[0].target_variable if context.forecasts else context.target_variable
    )
    target = lookup_target(target_variable)
    return FamilyForecast(
        family_id=context.family,
        decision_ts=context.decision_ts,
        target_variable=target.name,
        target_horizon=target.horizon,
        decision_unit=target.decision_unit,
        quantile_vector=None,
        abstain=True,
        abstain_reason=reason,
        contributing=[],
        excluded_desk_ids=[],
        abstaining_desk_ids=[],
        regime_posterior=context.regime_posterior or {"normal": 1.0},
        contract_hash=context.contract_hash,
        release_calendar_version=context.release_calendar_version,
    )


def _ttl_breached(context: MarketTickContext, ttl: timedelta) -> bool:
    if context.emitted_ts > context.decision_ts + ttl:
        return True
    if not context.forecasts:
        return False
    return any(context.emitted_ts > forecast.valid_until_ts for forecast in context.forecasts)


def _build_decision(
    *,
    context: MarketTickContext,
    family_forecast: FamilyForecast,
    raw_b_t: float | None,
    ttl_breached: bool,
    kill_halting: bool,
    new_exposure: ExposureState,
    control_params: ControlLawParams,
    ttl: timedelta,
    forecast_ids: tuple[str, ...],
) -> DecisionV2:
    target = lookup_target(family_forecast.target_variable)
    decision_abstain = (
        family_forecast.abstain
        or raw_b_t is None
        or ttl_breached
        or kill_halting
        or new_exposure.state != DegradationState.HEALTHY
    )
    abstain_reason = (
        _abstain_reason(context, family_forecast, ttl_breached, kill_halting, new_exposure)
        if decision_abstain
        else None
    )
    pred_scale = _pred_scale(family_forecast)
    signal_strength = None
    if family_forecast.quantile_vector is not None and pred_scale is not None:
        signal_strength = family_forecast.quantile_vector[3] / max(
            pred_scale, control_params.sigma_floor
        )

    return DecisionV2(
        family=context.family,
        decision_ts=context.decision_ts,
        target_variable=family_forecast.target_variable,
        target_horizon=family_forecast.target_horizon,
        decision_unit=family_forecast.decision_unit,
        instrument_spec=target.instrument_spec,
        roll_rule_id=context.roll_rule_id,
        target_risk_budget=None if decision_abstain else raw_b_t,
        abstain=decision_abstain,
        abstain_reason=abstain_reason,
        degradation_state=new_exposure.state,
        valid_until_ts=context.decision_ts + ttl,
        signal_strength=signal_strength,
        family_quantile_vector=family_forecast.quantile_vector,
        pred_scale=pred_scale,
        market_vol=context.market_vol_5d,
        calibration_multiplier=_weighted_contribution_avg(
            family_forecast, "calibration_score"
        ),
        data_quality_multiplier=_weighted_contribution_avg(
            family_forecast, "data_quality_score"
        ),
        roll_liquidity_multiplier=control_params.roll_liquidity_multiplier,
        regime_posterior=family_forecast.regime_posterior,
        hard_gates_passed=not decision_abstain,
        contributing_forecast_ids=list(forecast_ids),
        prereg_hash=context.prereg_hash,
        contract_hash=context.contract_hash,
    )


def _abstain_reason(
    context: MarketTickContext,
    family_forecast: FamilyForecast,
    ttl_breached: bool,
    kill_halting: bool,
    new_exposure: ExposureState,
) -> str:
    if kill_halting:
        reason = context.override_abstain_reason or context.kill_switch_state
        return reason if reason.startswith("kill_switch:") else f"kill_switch:{reason}"
    if ttl_breached:
        return "ttl_breached"
    if family_forecast.abstain_reason:
        return family_forecast.abstain_reason
    return new_exposure.state.value


def _cost_report(
    context: MarketTickContext,
    new_exposure: ExposureState,
    params: CostParams,
):
    return apply_costs(
        positions_before=np.array([float(context.prior_exposure.current_target)]),
        positions_after=np.array([float(new_exposure.current_target)]),
        gross_returns=np.array([float(context.realised_return_since_last_tick)]),
        realised_vols=np.array([float(context.market_vol_5d)]),
        params=params,
    )


def _ledger_record(
    *,
    context: MarketTickContext,
    decision: DecisionV2,
    new_exposure: ExposureState,
    lot_result,
    scenario: CostScenario,
    fill_cost: float,
    gross_return: float,
    net_return: float,
    forecast_ids: tuple[str, ...],
) -> LedgerRecord:
    return LedgerRecord(
        decision_ts=context.decision_ts,
        emitted_ts=context.emitted_ts,
        family=context.family,
        scenario=scenario,
        prior_target=context.prior_exposure.current_target,
        new_target=new_exposure.current_target,
        prior_lots=context.prior_lots,
        new_lots=lot_result.rounded_lots,
        raw_lots=lot_result.raw_lots,
        effective_b=lot_result.effective_b,
        price=context.price,
        market_vol_5d=context.market_vol_5d,
        fill_cost=fill_cost,
        gross_return=gross_return,
        net_return=net_return,
        degradation_state=new_exposure.state.value,
        forecast_ids=forecast_ids,
        abstain=decision.abstain,
        abstain_reason=decision.abstain_reason,
    )


def _pred_scale(family_forecast: FamilyForecast) -> float | None:
    if family_forecast.quantile_vector is None:
        return None
    return (family_forecast.quantile_vector[5] - family_forecast.quantile_vector[1]) / (
        _Z_90_05_WIDTH
    )


def _weighted_contribution_avg(family_forecast: FamilyForecast, attr: str) -> float:
    if not family_forecast.contributing:
        return 1.0
    return sum(
        contribution.weight_normalised * float(getattr(contribution, attr))
        for contribution in family_forecast.contributing
    )


def _source_manifest_hash(forecasts: list[ForecastV2]) -> str | None:
    if not forecasts:
        return None
    return content_hash(sorted(forecast.source_manifest_set_hash for forecast in forecasts))


def _require_utc(ts: datetime, name: str) -> None:
    if ts.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
