"""Replay ordering, gap, and timestamp quality helpers for S4 fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

IncidentSeverity = Literal["SEV0", "SEV1", "SEV2", "SEV3"]
GapKind = Literal[
    "time_gap_without_expected_sequence_break",
    "sequence_gap",
    "vendor_declared_gap",
    "missing_contract_segment",
    "maintenance_or_session_boundary_gap",
]


@dataclass(frozen=True)
class ReplayTick:
    symbol: str
    ts_event: datetime
    ts_recv: datetime | None
    vendor_row_number: int
    exchange_sequence_number: int | None = None
    vendor_declared_gap: bool = False
    maintenance_gap: bool = False

    def ordering_key(self) -> tuple[int, datetime, datetime, int]:
        sequence = (
            self.exchange_sequence_number
            if self.exchange_sequence_number is not None
            else 2**63 - 1
        )
        ts_recv = self.ts_recv or self.ts_event
        return (sequence, self.ts_event, ts_recv, self.vendor_row_number)


@dataclass(frozen=True)
class GapFinding:
    kind: GapKind
    severity: IncidentSeverity
    symbol: str
    detail: str
    vendor_row_number: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "symbol": self.symbol,
            "detail": self.detail,
            "vendor_row_number": self.vendor_row_number,
        }


@dataclass(frozen=True)
class TickQualityReport:
    input_rows: int
    duplicate_rows: int
    out_of_order_rows: int
    same_timestamp_groups: int
    sequence_gap_count: int
    vendor_declared_gap_count: int
    findings: tuple[GapFinding, ...] = field(default_factory=tuple)

    @property
    def has_material_gap(self) -> bool:
        return any(finding.severity in {"SEV0", "SEV1"} for finding in self.findings)

    def as_dict(self) -> dict[str, object]:
        return {
            "input_rows": self.input_rows,
            "duplicate_rows": self.duplicate_rows,
            "out_of_order_rows": self.out_of_order_rows,
            "same_timestamp_groups": self.same_timestamp_groups,
            "sequence_gap_count": self.sequence_gap_count,
            "vendor_declared_gap_count": self.vendor_declared_gap_count,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def analyze_tick_quality(
    ticks: list[ReplayTick],
    *,
    expected_symbols: set[str] | None = None,
    max_time_gap_without_sequence_break: timedelta | None = None,
    sequence_scope: Literal["global", "per_symbol"] = "per_symbol",
) -> TickQualityReport:
    findings: list[GapFinding] = []
    identities = [
        (
            tick.symbol,
            tick.exchange_sequence_number,
            tick.ts_event,
            tick.ts_recv,
            tick.vendor_row_number,
        )
        for tick in ticks
    ]
    duplicate_rows = len(identities) - len(set(identities))

    out_of_order_rows = 0
    prior_key: tuple[int, datetime, datetime, int] | None = None
    for tick in ticks:
        key = tick.ordering_key()
        if prior_key is not None and key < prior_key:
            out_of_order_rows += 1
        prior_key = key

    by_symbol: dict[str, list[ReplayTick]] = {}
    if sequence_scope == "global":
        by_symbol["*"] = sorted(ticks, key=lambda item: item.ordering_key())
    else:
        for tick in sorted(ticks, key=lambda item: (item.symbol, item.ordering_key())):
            by_symbol.setdefault(tick.symbol, []).append(tick)

    observed_symbols = {tick.symbol for tick in ticks}
    expected_symbols = expected_symbols or observed_symbols
    for symbol in sorted(expected_symbols - observed_symbols):
        findings.append(
            GapFinding(
                kind="missing_contract_segment",
                severity="SEV1",
                symbol=symbol,
                detail="expected symbol has no replay ticks",
            )
        )

    same_timestamp_groups = 0
    sequence_gap_count = 0
    vendor_declared_gap_count = 0
    for symbol, rows in by_symbol.items():
        timestamp_counts: dict[tuple[str, datetime], int] = {}
        for tick in rows:
            timestamp_key = (tick.symbol, tick.ts_event)
            timestamp_counts[timestamp_key] = timestamp_counts.get(timestamp_key, 0) + 1
            if tick.vendor_declared_gap:
                vendor_declared_gap_count += 1
                findings.append(
                    GapFinding(
                        kind="vendor_declared_gap",
                        severity="SEV1",
                        symbol=symbol,
                        detail="vendor declared a replay gap",
                        vendor_row_number=tick.vendor_row_number,
                    )
                )
        same_timestamp_groups += sum(1 for count in timestamp_counts.values() if count > 1)

        for previous, current in zip(rows, rows[1:], strict=False):
            if (
                previous.exchange_sequence_number is not None
                and current.exchange_sequence_number is not None
                and current.exchange_sequence_number > previous.exchange_sequence_number + 1
            ):
                sequence_gap_count += 1
                findings.append(
                    GapFinding(
                        kind="sequence_gap",
                        severity="SEV1",
                        symbol=symbol,
                        detail=(
                            f"sequence jumps from {previous.exchange_sequence_number} "
                            f"to {current.exchange_sequence_number}"
                        ),
                        vendor_row_number=current.vendor_row_number,
                    )
                )
            if max_time_gap_without_sequence_break is not None:
                gap = current.ts_event - previous.ts_event
                sequence_contiguous = (
                    previous.exchange_sequence_number is not None
                    and current.exchange_sequence_number is not None
                    and current.exchange_sequence_number == previous.exchange_sequence_number + 1
                )
                if gap > max_time_gap_without_sequence_break and sequence_contiguous:
                    kind: GapKind = (
                        "maintenance_or_session_boundary_gap"
                        if current.maintenance_gap
                        else "time_gap_without_expected_sequence_break"
                    )
                    findings.append(
                        GapFinding(
                            kind=kind,
                            severity="SEV3" if current.maintenance_gap else "SEV2",
                            symbol=symbol,
                            detail=f"time gap of {gap.total_seconds()} seconds",
                            vendor_row_number=current.vendor_row_number,
                        )
                    )

    return TickQualityReport(
        input_rows=len(ticks),
        duplicate_rows=duplicate_rows,
        out_of_order_rows=out_of_order_rows,
        same_timestamp_groups=same_timestamp_groups,
        sequence_gap_count=sequence_gap_count,
        vendor_declared_gap_count=vendor_declared_gap_count,
        findings=tuple(findings),
    )
