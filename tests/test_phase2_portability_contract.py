"""Phase 2 portability contract (spec §8.4).

The spec claims the shared infrastructure redeploys to equity-VRP with
**zero code changes**:

    §8.4: What does not change:
      - contracts/v1.py type definitions.
      - The bus.
      - The grading harness.
      - The attribution DB schema.
      - The research-loop trigger list.
      - The Controller's decision flow.
      - The sizing function.

This test operationalises that claim: it greps the shared-infra
packages for oil-specific vocabulary (WTI, CFTC, EIA, JODI, OPEC,
crude, barrel, etc.) and fails if any leaks in. Oil-specific strings
are permitted ONLY in `contracts/target_variables.py` (the registry is
domain-inclusive by design — v1.x revisions add equity-VRP target
constants alongside oil ones) and `desks/` (desk implementations are
fully replaced in Phase 2).

A Phase 2 redeployment that requires touching any shared-infra file
BECAUSE of domain-specific vocabulary is an abandon-trigger per
§12.3 point 4 ("`contracts/v1.py` needs a v2 bump"); this test
catches that regression before the Phase 2 calendar clock even
starts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# Packages whose contents MUST stay domain-neutral under §8.4.
# `sim/` is explicitly domain-specific (Phase-1 synthetic oil market
# simulator) and is replaced in Phase 2 — excluded.
# `desks/` is also replaced — excluded.
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

# Files inside `contracts/` that are allowed to reference oil vocab:
# target_variables.py is the registry. Everything else in contracts/
# must stay neutral.
CONTRACTS_OIL_ALLOWLIST = {"target_variables.py"}

# Oil-specific terms. Match case-insensitive whole-word-ish; "wti" and
# "cftc" are strictly oil/commodity terminology. "Crude" and "barrel"
# appear in realistic docstrings; "EIA" and "JODI" are agency acronyms.
# Excluded common-English words ("oil" alone appears in generic docs
# like "oil company"; we only scan shared-infra so that's fine).
OIL_TERMS = [
    "WTI",
    "Brent",
    "CFTC",
    "EIA",
    "JODI",
    "OPEC",
    "MOMR",
    "WPSR",
    "COT",
    "crude",
    "barrel",
]

# Compiled regex: case-insensitive word-boundary match
OIL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in OIL_TERMS) + r")\b",
    flags=re.IGNORECASE,
)


def _iter_python_files(dir_path: Path):
    for p in dir_path.rglob("*.py"):
        # Skip any __pycache__ directories
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
        for m in OIL_PATTERN.finditer(line):
            hits.append((lineno, m.group(1), line.strip()))
    return hits


@pytest.mark.parametrize("pkg", SHARED_INFRA_DIRS)
def test_shared_infra_package_has_no_oil_vocab(pkg):
    """Each shared-infra package must contain zero oil-specific terms."""
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
        f"Shared-infra package {pkg!r} contains oil-specific vocabulary; "
        f"these are §8.4 portability violations:\n  " + "\n  ".join(violations)
    )


def test_contracts_package_neutral_except_target_variables():
    """contracts/ is domain-neutral except for target_variables.py
    (the frozen registry that legitimately lists oil targets and will
    grow equity-VRP targets in v1.x)."""
    contracts_path = REPO_ROOT / "contracts"
    violations: list[str] = []
    for py_file in _iter_python_files(contracts_path):
        if py_file.name in CONTRACTS_OIL_ALLOWLIST:
            continue
        hits = _scan_file(py_file)
        for lineno, term, line in hits:
            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {term!r} in {line!r}")
    assert not violations, (
        "contracts/ files outside the target_variables.py allowlist "
        "contain oil-specific vocabulary:\n  " + "\n  ".join(violations)
    )


def test_shared_infra_imports_do_not_reach_into_desks():
    """Shared-infra packages must not import from `desks.*`. Desks
    are fully replaced in Phase 2; any shared-infra dependency on
    desks would force a rewrite."""
    forbidden_import = re.compile(r"^(from|import)\s+desks(\.|$|\s)")
    violations: list[str] = []
    for pkg in SHARED_INFRA_DIRS:
        pkg_path = REPO_ROOT / pkg
        if not pkg_path.is_dir():
            continue
        for py_file in _iter_python_files(pkg_path):
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if forbidden_import.match(stripped):
                    violations.append(f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {stripped!r}")
    assert not violations, (
        "Shared-infra packages import from desks.* — that breaks §8.4 "
        "zero-code-change portability:\n  " + "\n  ".join(violations)
    )


def test_target_variable_registry_is_single_source_of_truth():
    """Every oil constant (WTI_*, *_CLOSE, etc.) must be declared in
    contracts/target_variables.py and imported from there, never
    re-declared. Catches duplicates that would drift under Phase 2."""
    registry = REPO_ROOT / "contracts" / "target_variables.py"
    assert registry.is_file(), "contracts/target_variables.py must exist"
    registry_text = registry.read_text()
    # Pull known constant names from the registry (simple heuristic: UPPER_CASE = "...")
    const_pattern = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)
    constants = {m.group(1) for m in const_pattern.finditer(registry_text)}
    # At minimum the WTI_FRONT_MONTH_CLOSE constant must be present
    # (it's referenced across the codebase).
    assert "WTI_FRONT_MONTH_CLOSE" in constants, (
        f"WTI_FRONT_MONTH_CLOSE not found in registry; got {constants}"
    )

    # Check no other file re-declares these constants
    duplicates: list[str] = []
    for pkg in SHARED_INFRA_DIRS + ["contracts"]:
        pkg_path = REPO_ROOT / pkg
        if not pkg_path.is_dir():
            continue
        for py_file in _iter_python_files(pkg_path):
            if py_file == registry:
                continue
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                # Pattern: UPPER_CASE_NAME = "..." or = f"..."
                m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=", stripped)
                if m and m.group(1) in constants:
                    duplicates.append(
                        f"{py_file.relative_to(REPO_ROOT)}:{lineno}: re-declares {m.group(1)!r}"
                    )
    assert not duplicates, (
        "Oil target constants re-declared outside the registry:\n  " + "\n  ".join(duplicates)
    )
