"""Phase 2 equity-VRP portability contract (spec §8.4 + v1.12 §14.7).

Mirror of `test_phase2_portability_contract.py` — the oil version — but
scanning shared-infra for **equity-VRP** vocabulary leakage. Runs
alongside the oil contract; both must pass at all times.

If a Phase 2 desk implementation leaks equity-VRP vocabulary into
`bus/`, `controller/`, `persistence/`, etc., this test fails BEFORE a
code review sees the diff. Oil-specific strings are permitted ONLY in
`contracts/target_variables.py` (registry is domain-inclusive by
design — same allowlist as the oil test).

A Phase 2 redeployment requiring equity-VRP-aware shared infra would
be a §12.3 point 4 abandon-trigger. This test catches it at commit
time, not at integration time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# Packages whose contents MUST stay domain-neutral under §8.4.
# `sim/` (oil-specific) and `sim_equity_vrp/` (equity-specific) are
# both explicitly domain-scoped simulator packages and are excluded.
# `desks/` is replaced in Phase 2 — excluded.
SHARED_INFRA_DIRS = [
    "bus",
    "controller",
    "attribution",
    "research_loop",
    "persistence",
    "soak",
    "grading",
    "scheduler",
    "eval",
    "provenance",
]

# Files inside `contracts/` that are allowed to reference equity-VRP
# vocab: target_variables.py is the registry. Everything else in
# contracts/ must stay neutral.
CONTRACTS_EQUITY_VRP_ALLOWLIST = {"target_variables.py"}

# Equity-VRP vocabulary. "VRP" is the tightest single identifier;
# "VIX" and "SPX" are underlying ticker names; "vega" / "skew" are
# options terminology; "dealer" / "implied" / "realized" (with the
# _vol suffix) are specific to the vol-risk-premium domain.
EQUITY_VRP_TERMS = [
    "VIX",
    "SPX",
    "vega",
    "skew",
    "dealer_flow",
    "dealer_inventory",
    "implied_vol",
    "realized_vol",
    "vol_regime",
    "vol_stress",
    "vol_quiet",
    "vol_recovery",
    "VRP",
    # v1.13 additions for hedging_demand desk:
    "hedging",
    "hedging_demand",
    "put_skew",
    "open_interest",
    "put_call_ratio",
]

EQUITY_VRP_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in EQUITY_VRP_TERMS) + r")\b",
    flags=re.IGNORECASE,
)


def _iter_python_files(dir_path: Path):
    for p in dir_path.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _iter_sql_files(dir_path: Path):
    yield from dir_path.rglob("*.sql")


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_number, term, line_content) for each match."""
    hits: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in EQUITY_VRP_PATTERN.finditer(line):
            hits.append((lineno, m.group(1), line.strip()))
    return hits


@pytest.mark.parametrize("pkg", SHARED_INFRA_DIRS)
def test_shared_infra_package_has_no_equity_vrp_vocab(pkg):
    """Each shared-infra package must contain zero equity-VRP-specific terms."""
    pkg_path = REPO_ROOT / pkg
    if not pkg_path.is_dir():
        pytest.skip(f"{pkg} not present in repo")
    violations: list[str] = []
    for py_file in _iter_python_files(pkg_path):
        hits = _scan_file(py_file)
        for lineno, term, line in hits:
            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {term!r} in {line!r}")
    for sql_file in _iter_sql_files(pkg_path):
        hits = _scan_file(sql_file)
        for lineno, term, line in hits:
            violations.append(f"{sql_file.relative_to(REPO_ROOT)}:{lineno}: {term!r} in {line!r}")
    assert not violations, (
        f"Shared-infra package {pkg!r} contains equity-VRP vocabulary; "
        f"these are §8.4 portability violations:\n  " + "\n  ".join(violations)
    )


def test_contracts_package_neutral_except_target_variables():
    """contracts/ is domain-neutral except for target_variables.py
    (the frozen registry that lists equity-VRP targets alongside oil
    ones by design)."""
    contracts_path = REPO_ROOT / "contracts"
    violations: list[str] = []
    for py_file in _iter_python_files(contracts_path):
        if py_file.name in CONTRACTS_EQUITY_VRP_ALLOWLIST:
            continue
        hits = _scan_file(py_file)
        for lineno, term, line in hits:
            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {term!r} in {line!r}")
    assert not violations, (
        "contracts/ files outside the target_variables.py allowlist "
        "contain equity-VRP vocabulary:\n  " + "\n  ".join(violations)
    )


def test_hedging_demand_routed_on_feed_failure():
    """v1.13 routing regression: when the scheduler emits a
    data_ingestion_failure for either of hedging_demand's feeds
    (`cboe_open_interest`, `option_volume`), the outbound payload's
    `affected_desks` must include `"hedging_demand"`. Proves the
    config/data_sources.yaml registration wires correctly through the
    scheduler → handler flow — otherwise the desk's staleness hooks
    are decorative."""
    from datetime import UTC, datetime

    from scheduler import Scheduler

    sched = Scheduler.from_config()
    ts = datetime(2026, 4, 18, 14, 0, 0, tzinfo=UTC)
    for feed in ("cboe_open_interest", "option_volume"):
        event = sched.emit_ingestion_failure(feed, ts, ts)
        affected = event.payload["affected_desks"]
        assert isinstance(affected, list)
        assert "hedging_demand" in affected, (
            f"feed={feed!r}: scheduler payload affected_desks does not route to "
            f"hedging_demand; got {affected}. Did config/data_sources.yaml "
            f"get the consumed_by entry?"
        )


def test_equity_vrp_target_constants_live_in_registry():
    """VIX_30D_FORWARD and SPX_30D_IMPLIED_VOL must live only in
    contracts/target_variables.py and be members of KNOWN_TARGETS.
    Mirror of the oil test's single-source-of-truth rule."""
    from contracts.target_variables import (
        KNOWN_TARGETS,
        SPX_30D_IMPLIED_VOL,
        VIX_30D_FORWARD,
    )

    assert VIX_30D_FORWARD in KNOWN_TARGETS
    assert SPX_30D_IMPLIED_VOL in KNOWN_TARGETS

    # Check no other file re-declares these constants.
    names = ["VIX_30D_FORWARD", "SPX_30D_IMPLIED_VOL"]
    duplicates: list[str] = []
    for pkg in SHARED_INFRA_DIRS + ["contracts"]:
        pkg_path = REPO_ROOT / pkg
        if not pkg_path.is_dir():
            continue
        for py_file in _iter_python_files(pkg_path):
            if py_file.name == "target_variables.py":
                continue
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=", stripped)
                if m and m.group(1) in names:
                    duplicates.append(
                        f"{py_file.relative_to(REPO_ROOT)}:{lineno}: re-declares {m.group(1)!r}"
                    )
    assert not duplicates, (
        "Equity-VRP target constants re-declared outside the registry:\n  "
        + "\n  ".join(duplicates)
    )
