"""Layer-1 PIT audit.

The Layer-1 gate per docs/v2/promotion_lifecycle.md §4: every feature
used by a promoting desk must have a reconstructible vintage history,
a per-source release-lag distribution, revision statistics, and 100%
schema + checksum coverage. The audit also names the earliest
decision-eligible `as_of_ts` at which the desk's full feature view is
reconstructible — this defines the v2.0 training window.

The auditor is deliberately source-agnostic. It consumes the
`pit_manifest` table plus the release-calendar dict; it does not need
to know what a desk is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from v2.pit_store.manifest import PITManifest
from v2.pit_store.reader import PITReader
from v2.pit_store.release_calendar import ReleaseCalendar, load_calendars_dir


@dataclass
class SourceAudit:
    source: str
    vintage_count: int
    first_release_ts: datetime | None
    last_release_ts: datetime | None
    revision_count: int
    superseded_count: int
    checksum_failures: int
    schema_hash_variants: int
    release_lag_p50_days: float | None
    release_lag_p95_days: float | None
    calendar_present: bool


@dataclass
class PITAuditReport:
    generated_at: datetime
    sources: dict[str, SourceAudit] = field(default_factory=dict)
    feature_requirements: dict[str, str] = field(default_factory=dict)
    earliest_reconstructible_as_of: datetime | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def to_json(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "earliest_reconstructible_as_of": (
                self.earliest_reconstructible_as_of.isoformat()
                if self.earliest_reconstructible_as_of
                else None
            ),
            "feature_requirements": self.feature_requirements,
            "sources": {
                s: {
                    "vintage_count": a.vintage_count,
                    "first_release_ts": a.first_release_ts.isoformat()
                    if a.first_release_ts
                    else None,
                    "last_release_ts": a.last_release_ts.isoformat() if a.last_release_ts else None,
                    "revision_count": a.revision_count,
                    "superseded_count": a.superseded_count,
                    "checksum_failures": a.checksum_failures,
                    "schema_hash_variants": a.schema_hash_variants,
                    "release_lag_p50_days": a.release_lag_p50_days,
                    "release_lag_p95_days": a.release_lag_p95_days,
                    "calendar_present": a.calendar_present,
                }
                for s, a in self.sources.items()
            },
            "issues": list(self.issues),
            "is_clean": self.is_clean,
        }


class PITAuditor:
    def __init__(
        self,
        pit_root: Path,
        manifest: PITManifest,
        calendars: dict[str, ReleaseCalendar],
    ):
        self.pit_root = Path(pit_root)
        self.manifest = manifest
        self.calendars = calendars
        self.reader = PITReader(pit_root, manifest)

    @classmethod
    def from_pit_root(cls, pit_root: Path, calendars_dir: Path) -> PITAuditor:
        manifest = PITManifest.open(pit_root)
        calendars = load_calendars_dir(calendars_dir)
        return cls(pit_root, manifest, calendars)

    def audit(self, feature_requirements: dict[str, str] | None = None) -> PITAuditReport:
        """Run the Layer-1 audit.

        `feature_requirements` is a mapping of `feature_name -> source`;
        every source listed must have a calendar + at least one vintage
        + checksum coverage for all vintages. If omitted, the audit
        reports every source present in the manifest (no per-feature
        completeness check).
        """
        report = PITAuditReport(
            generated_at=_utcnow(),
            feature_requirements=feature_requirements or {},
        )

        rows = self.manifest.list_all()
        if not rows:
            report.issues.append("manifest is empty; nothing to audit")
            return report

        by_source: dict[str, list] = {}
        for r in rows:
            by_source.setdefault(r.source, []).append(r)

        for source, source_rows in by_source.items():
            release_ts_list = [r.release_ts for r in source_rows]
            lag_days = [
                max((r.ingest_ts - r.release_ts).total_seconds() / 86400.0, 0.0)
                for r in source_rows
            ]
            schema_hashes = {r.schema_hash for r in source_rows}
            revisions = [r for r in source_rows if r.revision_ts is not None]
            superseded = [r for r in source_rows if r.superseded_by is not None]

            checksum_failures = 0
            for r in source_rows:
                try:
                    _ = self.reader._verified_parquet(r)  # noqa: SLF001
                except Exception as exc:
                    checksum_failures += 1
                    report.issues.append(f"{source}:{r.manifest_id}: checksum or file error: {exc}")

            audit = SourceAudit(
                source=source,
                vintage_count=len(source_rows),
                first_release_ts=min(release_ts_list),
                last_release_ts=max(release_ts_list),
                revision_count=len(revisions),
                superseded_count=len(superseded),
                checksum_failures=checksum_failures,
                schema_hash_variants=len(schema_hashes),
                release_lag_p50_days=(_pct(lag_days, 0.5) if lag_days else None),
                release_lag_p95_days=(_pct(lag_days, 0.95) if lag_days else None),
                calendar_present=source in self.calendars,
            )
            report.sources[source] = audit
            if not audit.calendar_present:
                report.issues.append(f"{source}: no release calendar under v2/pit_store/calendars/")

        # Check feature requirements
        for feat, src in (feature_requirements or {}).items():
            if src not in report.sources:
                report.issues.append(
                    f"feature '{feat}': required source '{src}' has no vintages in manifest"
                )

        # Earliest reconstructible as_of: the latest first_release_ts
        # across all required sources (so every feature is eligible).
        required_sources = set((feature_requirements or {}).values()) or set(report.sources.keys())
        firsts = [
            report.sources[s].first_release_ts
            for s in required_sources
            if s in report.sources and report.sources[s].first_release_ts is not None
        ]
        report.earliest_reconstructible_as_of = max(firsts) if firsts else None

        return report


# -- helpers ------------------------------------------------------------------


def _pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return float(pd.Series(s).quantile(p))


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
