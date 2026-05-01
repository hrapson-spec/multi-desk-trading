"""PIT store reader: as-of-safe vintage queries.

Core query shape: given a decision timestamp `ts` and a source/series
identifier, return the data that was decision-eligible at `ts`. Every read
verifies the Parquet file's checksum against the manifest; a mismatch
raises PITChecksumError (consumed as a hard-gate trigger under
docs/v2/kill_switch_and_rollback.md KS-D02).

Eligibility rule (reference implementation; docs/v2/v2_data_contract.md §4
is refined by this wording):

    known_by_ts = COALESCE(revision_ts, usable_after_ts)

    A row is decision-eligible at ts iff usable_after_ts <= ts AND
    known_by_ts <= ts. Within each release_ts group, the row with the
    largest known_by_ts wins. The most recent release_ts group wins overall.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from v2.pit_store.manifest import MANIFEST_SELECT, ManifestRow, PITManifest


class PITChecksumError(Exception):
    """On-disk Parquet checksum does not match the manifest. Corruption
    or out-of-band mutation. Consumes as KS-D02 per the kill-switch spec."""


@dataclass(frozen=True)
class DataQuality:
    source: str
    dataset: str | None
    release_ts: datetime
    usable_after_ts: datetime
    revision_ts: datetime | None
    as_of_ts: datetime
    release_lag_days: float
    freshness_state: str  # fresh | stale_1w | stale_2w | stale_over_2w
    decision_eligible: bool
    checksum_verified: bool
    quality_multiplier: float
    vintage_quality: str
    # Placeholder slots populated by desk-side logic once the calendar
    # declares its per-condition multipliers (v2.1+):
    source_confidence: float = 1.0
    forward_fill_used: bool = False
    missingness_mask: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReadResult:
    data: pd.DataFrame
    manifest: ManifestRow
    data_quality: DataQuality


class PITReader:
    def __init__(self, pit_root: Path, manifest: PITManifest):
        self.pit_root = Path(pit_root)
        self.manifest = manifest

    def as_of(
        self,
        source: str,
        series: str | None,
        as_of_ts: datetime,
        *,
        dataset: str | None = None,
    ) -> ReadResult | None:
        """Return the decision-eligible vintage for (source, series) at `as_of_ts`,
        or None if no vintage is eligible.

        Eligibility comparator is `known_by_ts = COALESCE(revision_ts, usable_after_ts)`
        — first-release vintages become known at usable_after_ts; revisions
        become known at their revision_ts (the wall-clock moment the correction
        was observed). Among rows eligible at `as_of_ts`, the row with the
        largest `known_by_ts` wins within each release_ts group, and the
        most recent release_ts group wins overall.
        """
        ts = _to_utc(as_of_ts)
        ts_naive = ts.replace(tzinfo=None)
        row = self.manifest.conn.execute(
            f"""
            WITH eligible AS (
                SELECT m.*,
                       COALESCE(m.revision_ts, m.usable_after_ts) AS known_by_ts
                FROM pit_manifest m
                WHERE m.source = ?
                  AND (? IS NULL OR m.dataset = ?)
                  AND ((? IS NULL AND m.series IS NULL) OR m.series = ?)
                  AND m.usable_after_ts <= ?
                  AND COALESCE(m.revision_ts, m.usable_after_ts) <= ?
            ),
            per_observation_winner AS (
                SELECT e.*
                FROM eligible e
                JOIN (
                    SELECT release_ts, observation_end, MAX(known_by_ts) AS best
                    FROM eligible
                    GROUP BY release_ts, observation_end
                ) g
                  ON e.release_ts = g.release_ts
                 AND (
                     (e.observation_end IS NULL AND g.observation_end IS NULL)
                     OR e.observation_end = g.observation_end
                 )
                 AND e.known_by_ts = g.best
            )
            SELECT {MANIFEST_SELECT}
            FROM per_observation_winner
            ORDER BY release_ts DESC, observation_end DESC NULLS LAST, known_by_ts DESC
            LIMIT 1
            """,
            [source, dataset, dataset, series, series, ts_naive, ts_naive],
        ).fetchone()
        if row is None:
            return None
        manifest_row = ManifestRow.from_row(row)
        return self._load(manifest_row, ts)

    def latest_available_before(
        self,
        source: str,
        series: str | None,
        before_ts: datetime,
        *,
        dataset: str | None = None,
    ) -> ReadResult | None:
        """Return the latest vintage with release_ts STRICTLY before `before_ts`.

        Unlike as_of, this ignores supersession; it returns whichever
        release arrived most recently before the cutoff, including rows
        that were later revised.
        """
        ts = _to_utc(before_ts)
        ts_naive = ts.replace(tzinfo=None)
        row = self.manifest.conn.execute(
            f"""
            SELECT {MANIFEST_SELECT}
            FROM pit_manifest
            WHERE source = ?
              AND (? IS NULL OR dataset = ?)
              AND ((? IS NULL AND series IS NULL) OR series = ?)
              AND release_ts < ?
            ORDER BY release_ts DESC, observation_end DESC NULLS LAST, revision_ts DESC NULLS LAST
            LIMIT 1
            """,
            [source, dataset, dataset, series, series, ts_naive],
        ).fetchone()
        if row is None:
            return None
        manifest_row = ManifestRow.from_row(row)
        return self._load(manifest_row, ts)

    def vintage_diff(
        self,
        source: str,
        series: str | None,
        vintage_a: datetime,
        vintage_b: datetime,
        *,
        dataset: str | None = None,
    ) -> pd.DataFrame:
        """Load both vintages by their release_ts and return a row-level diff.

        The return is the outer-joined diff with a `side` column in
        {"left_only", "right_only", "both_differ", "both_match"}.
        """
        row_a = self._row_by_release_ts(source, series, vintage_a, dataset=dataset)
        row_b = self._row_by_release_ts(source, series, vintage_b, dataset=dataset)
        if row_a is None or row_b is None:
            raise LookupError(f"vintage_diff missing vintage: a={row_a}, b={row_b}")
        a = self._verified_parquet(row_a)
        b = self._verified_parquet(row_b)
        return _frame_diff(a, b)

    # -- internal -------------------------------------------------------------

    def _row_by_release_ts(
        self,
        source: str,
        series: str | None,
        release_ts: datetime,
        *,
        dataset: str | None = None,
    ) -> ManifestRow | None:
        return self.manifest.find_first_release(source, series, release_ts, dataset=dataset) or None

    def _load(self, manifest_row: ManifestRow, as_of_ts: datetime) -> ReadResult:
        data = self._verified_parquet(manifest_row)
        dq = _build_data_quality(manifest_row, as_of_ts, checksum_verified=True)
        return ReadResult(data=data, manifest=manifest_row, data_quality=dq)

    def _verified_parquet(self, manifest_row: ManifestRow) -> pd.DataFrame:
        path = self.pit_root / manifest_row.parquet_path
        if not path.exists():
            raise FileNotFoundError(f"parquet missing: {path}")
        actual = _sha256_file(path)
        if actual != manifest_row.checksum:
            raise PITChecksumError(
                f"{path}: manifest checksum {manifest_row.checksum} != on-disk checksum {actual}"
            )
        return pd.read_parquet(path)


# -- helpers ------------------------------------------------------------------


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _sha256_file(path: Path, chunk: int = 2**20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _build_data_quality(
    row: ManifestRow, as_of_ts: datetime, *, checksum_verified: bool
) -> DataQuality:
    # Freshness is a function of (as_of_ts - usable_after_ts). The exact
    # per-source bands are declared in the release calendar; v2.0 ships
    # a conservative default fall-back here. When a calendar-aware reader
    # wrapper is added, these bands move out of this function.
    lag_days = max((as_of_ts - row.usable_after_ts).total_seconds() / 86400.0, 0.0)
    if lag_days <= 7:
        freshness = "fresh"
    elif lag_days <= 14:
        freshness = "stale_1w"
    elif lag_days <= 28:
        freshness = "stale_2w"
    else:
        freshness = "stale_over_2w"
    # Default multiplier table (overridden per-source by the calendar):
    default_multiplier = {
        "fresh": 1.0,
        "stale_1w": 0.85,
        "stale_2w": 0.60,
        "stale_over_2w": 0.0,
    }
    return DataQuality(
        source=row.source,
        dataset=row.dataset,
        release_ts=row.release_ts,
        usable_after_ts=row.usable_after_ts,
        revision_ts=row.revision_ts,
        as_of_ts=as_of_ts,
        release_lag_days=lag_days,
        freshness_state=freshness,
        decision_eligible=row.usable_after_ts <= as_of_ts,
        checksum_verified=checksum_verified,
        quality_multiplier=default_multiplier[freshness],
        vintage_quality=row.vintage_quality,
    )


def _frame_diff(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Row-level outer join diff. Columns must match; otherwise a ValueError."""
    if list(a.columns) != list(b.columns):
        raise ValueError(
            f"vintage_diff column mismatch: a={list(a.columns)} vs b={list(b.columns)}"
        )
    # Use an index-based alignment if both frames share an index name;
    # otherwise fall back to a positional concat-with-marker.
    if a.index.name is not None and a.index.name == b.index.name:
        merged = a.join(b, how="outer", lsuffix="_a", rsuffix="_b", sort=True)
        return merged
    a_tagged = a.copy()
    a_tagged["__side"] = "a"
    b_tagged = b.copy()
    b_tagged["__side"] = "b"
    return pd.concat([a_tagged, b_tagged], ignore_index=True)
