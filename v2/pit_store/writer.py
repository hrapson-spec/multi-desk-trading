"""PIT store writer: ingest raw Parquet vintages.

Each `write_vintage` call atomically:
    1. Writes the DataFrame to a canonical path under `pit_root/raw/...`.
    2. Computes SHA-256 over the on-disk Parquet bytes.
    3. Computes a schema_hash over the sorted dtype map.
    4. Inserts a manifest row.
    5. If a first-release vintage for the same
       (source, dataset, series, release_ts, observation_start,
       observation_end) already exists, the new write is treated as a
       revision, its `revision_ts` is set, and the older row is marked
       superseded.

The canonical path is stable: re-ingesting an identical vintage byte-for-byte
overwrites the same file and the checksum stays constant. Re-ingesting with
a different payload raises PITChecksumMismatch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from v2.pit_store.manifest import MANIFEST_SELECT, ManifestRow, PITManifest, new_manifest_id
from v2.pit_store.quality import VintageQuality, coerce_vintage_quality


class PITChecksumMismatchError(Exception):
    """Re-ingest of the same (source, series, release_ts, revision_ts)
    produced different bytes. Indicates upstream data instability or a
    scraper change that must be handled via a typed deviation."""


# Backwards-compatible alias (exported name in __init__.py and tests).
PITChecksumMismatch = PITChecksumMismatchError


@dataclass(frozen=True)
class WriteResult:
    manifest_id: str
    parquet_path: str
    checksum: str
    schema_hash: str
    row_count: int
    source: str
    dataset: str | None
    series: str | None
    vintage_quality: str
    was_revision: bool
    superseded_manifest_id: str | None


class PITWriter:
    def __init__(self, pit_root: Path, manifest: PITManifest):
        self.pit_root = Path(pit_root)
        self.manifest = manifest
        (self.pit_root / "raw").mkdir(parents=True, exist_ok=True)

    def write_vintage(
        self,
        *,
        source: str,
        dataset: str | None = None,
        series: str | None,
        release_ts: datetime,
        data: pd.DataFrame,
        provenance: dict,
        vintage_quality: str | VintageQuality = VintageQuality.TRUE_FIRST_RELEASE,
        usable_after_ts: datetime | None = None,
        revision_ts: datetime | None = None,
        observation_start: date | None = None,
        observation_end: date | None = None,
        ingest_ts: datetime | None = None,
    ) -> WriteResult:
        if data is None or data.empty:
            raise ValueError("cannot write empty DataFrame")
        if not source:
            raise ValueError("source is required")
        if "source" not in provenance or "method" not in provenance:
            raise ValueError(
                "provenance must include at least 'source' and 'method' keys "
                "(see v2_data_contract §10)"
            )
        vintage_quality_value = coerce_vintage_quality(vintage_quality).value

        release_ts_utc = _to_utc(release_ts)
        usable_after_ts_utc = (
            _to_utc(usable_after_ts) if usable_after_ts is not None else release_ts_utc
        )
        ingest_ts_utc = _to_utc(ingest_ts) if ingest_ts is not None else _utcnow()

        # Stage 1: write to a temp file so we can checksum before commit.
        tmp_dir = self.pit_root / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        import uuid as _uuid

        tmp_path = tmp_dir / f"{_uuid.uuid4().hex}.parquet"
        table = pa.Table.from_pandas(data, preserve_index=False)
        pq.write_table(
            table,
            tmp_path,
            compression="snappy",
            use_dictionary=True,
            write_statistics=False,
        )
        checksum = _sha256_file(tmp_path)
        schema_hash = _schema_hash(data)
        row_count = len(data)

        # Stage 2: classify this write against what's already in the manifest.
        #
        #   - If caller provided revision_ts, the target slot is exact.
        #     If that slot exists with matching checksum: idempotent no-op.
        #     If that slot exists with different checksum: PITChecksumMismatch.
        #     If that slot does not exist: insert as a revision (supersedes the
        #     current first-release if one exists).
        #
        #   - If caller did NOT provide revision_ts, the target slot is the
        #     first-release (revision_ts IS NULL) for this observation period.
        #     If no first-release exists: first write; insert with revision_ts=NULL.
        #     If first-release exists with matching checksum: idempotent no-op.
        #     If first-release exists with different checksum: this is a
        #     revision; auto-assign revision_ts=ingest_ts and insert as revision.
        existing_first = self.manifest.find_first_release(
            source,
            series,
            release_ts_utc,
            dataset=dataset,
            observation_start=observation_start,
            observation_end=observation_end,
        )

        if revision_ts is None:
            if existing_first is None:
                is_revision = False
                revision_ts_utc = None
            elif existing_first.checksum == checksum:
                tmp_path.unlink(missing_ok=True)
                return WriteResult(
                    manifest_id=existing_first.manifest_id,
                    parquet_path=existing_first.parquet_path,
                    checksum=existing_first.checksum,
                    schema_hash=existing_first.schema_hash,
                    row_count=existing_first.row_count,
                    source=existing_first.source,
                    dataset=existing_first.dataset,
                    series=existing_first.series,
                    vintage_quality=existing_first.vintage_quality,
                    was_revision=False,
                    superseded_manifest_id=None,
                )
            else:
                is_revision = True
                revision_ts_utc = ingest_ts_utc
        else:
            # Caller specified revision_ts explicitly.
            revision_ts_utc = _to_utc(revision_ts)
            is_revision = True
            existing_slot = self._find_exact_slot(
                source,
                dataset,
                series,
                release_ts_utc,
                revision_ts_utc,
                observation_start=observation_start,
                observation_end=observation_end,
            )
            if existing_slot is not None:
                if existing_slot.checksum == checksum:
                    tmp_path.unlink(missing_ok=True)
                    return WriteResult(
                        manifest_id=existing_slot.manifest_id,
                        parquet_path=existing_slot.parquet_path,
                        checksum=existing_slot.checksum,
                        schema_hash=existing_slot.schema_hash,
                        row_count=existing_slot.row_count,
                        source=existing_slot.source,
                        dataset=existing_slot.dataset,
                        series=existing_slot.series,
                        vintage_quality=existing_slot.vintage_quality,
                        was_revision=True,
                        superseded_manifest_id=None,
                    )
                tmp_path.unlink(missing_ok=True)
                raise PITChecksumMismatch(
                    f"re-ingest of ({source}, {dataset}, {series}, {release_ts_utc.isoformat()}, "
                    f"rev={revision_ts_utc.isoformat()}) produced checksum "
                    f"{checksum}, manifest has {existing_slot.checksum}"
                )

        # Stage 3: promote temp to canonical path.
        parquet_rel = _canonical_path(source, dataset, series, release_ts_utc, revision_ts_utc)
        parquet_abs = self.pit_root / parquet_rel
        parquet_abs.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.replace(parquet_abs)

        manifest_id = new_manifest_id()
        row = ManifestRow(
            manifest_id=manifest_id,
            source=source,
            dataset=dataset,
            series=series,
            release_ts=release_ts_utc,
            usable_after_ts=usable_after_ts_utc,
            revision_ts=revision_ts_utc,
            observation_start=observation_start,
            observation_end=observation_end,
            schema_hash=schema_hash,
            row_count=row_count,
            checksum=checksum,
            ingest_ts=ingest_ts_utc,
            provenance=provenance,
            parquet_path=parquet_rel,
            vintage_quality=vintage_quality_value,
            superseded_by=None,
        )
        self.manifest.insert(row)

        superseded_id: str | None = None
        if is_revision:
            assert existing_first is not None
            self.manifest.supersede(existing_first.manifest_id, manifest_id)
            superseded_id = existing_first.manifest_id

        return WriteResult(
            manifest_id=manifest_id,
            parquet_path=parquet_rel,
            checksum=checksum,
            schema_hash=schema_hash,
            row_count=row_count,
            source=source,
            dataset=dataset,
            series=series,
            vintage_quality=vintage_quality_value,
            was_revision=is_revision,
            superseded_manifest_id=superseded_id,
        )

    # -- internal helpers -----------------------------------------------------

    def _find_exact_slot(
        self,
        source: str,
        dataset: str | None,
        series: str | None,
        release_ts: datetime,
        revision_ts: datetime | None,
        observation_start: date | None = None,
        observation_end: date | None = None,
    ) -> ManifestRow | None:
        if revision_ts is None:
            return self.manifest.find_first_release(
                source,
                series,
                release_ts,
                dataset=dataset,
                observation_start=observation_start,
                observation_end=observation_end,
            )
        rows = self.manifest.conn.execute(
            f"""
            SELECT {MANIFEST_SELECT} FROM pit_manifest
            WHERE source = ?
              AND ((? IS NULL AND dataset IS NULL) OR dataset = ?)
              AND ((? IS NULL AND series IS NULL) OR series = ?)
              AND release_ts = ?
              AND (? IS NULL OR observation_start = ?)
              AND (? IS NULL OR observation_end = ?)
              AND revision_ts = ?
            """,
            [
                source,
                dataset,
                dataset,
                series,
                series,
                _naive_utc(release_ts),
                observation_start,
                observation_start,
                observation_end,
                observation_end,
                _naive_utc(revision_ts),
            ],
        ).fetchone()
        return ManifestRow.from_row(rows) if rows is not None else None


# -- helpers ------------------------------------------------------------------


def _canonical_path(
    source: str,
    dataset: str | None,
    series: str | None,
    release_ts: datetime,
    revision_ts: datetime | None,
) -> str:
    iso = release_ts.strftime("%Y-%m-%dT%H-%M-%SZ")
    parts = [f"raw/{source}"]
    if dataset is not None:
        parts.append(f"dataset={dataset}")
    if series is not None:
        parts.append(f"series={series}")
    parts.append(f"release_ts={iso}")
    if revision_ts is not None:
        rev_iso = revision_ts.strftime("%Y-%m-%dT%H-%M-%SZ")
        parts.append(f"revision_ts={rev_iso}")
    parts.append("data.parquet")
    return "/".join(parts)


def _sha256_file(path: Path, chunk: int = 2**20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _schema_hash(df: pd.DataFrame) -> str:
    spec = "|".join(f"{c}:{df[c].dtype}" for c in sorted(df.columns))
    return hashlib.sha256(spec.encode("utf-8")).hexdigest()


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _naive_utc(ts: datetime) -> datetime:
    return _to_utc(ts).replace(tzinfo=None)


def _utcnow() -> datetime:
    return datetime.now(UTC)
