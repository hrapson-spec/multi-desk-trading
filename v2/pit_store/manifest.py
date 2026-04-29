"""Bitemporal manifest for the v2 PIT store.

Schema governed by docs/v2/v2_data_contract.md §2. A manifest row is the
authoritative metadata for a raw Parquet vintage; the Parquet bytes
themselves are canonical truth.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from v2.pit_store.quality import coerce_vintage_quality

MANIFEST_DDL = """
CREATE TABLE IF NOT EXISTS pit_manifest (
    manifest_id       TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    dataset           TEXT,
    series            TEXT,
    release_ts        TIMESTAMP NOT NULL,
    usable_after_ts   TIMESTAMP,
    revision_ts       TIMESTAMP,
    observation_start DATE,
    observation_end   DATE,
    schema_hash       TEXT NOT NULL,
    row_count         BIGINT NOT NULL,
    checksum          TEXT NOT NULL,
    ingest_ts         TIMESTAMP NOT NULL,
    provenance        TEXT NOT NULL,
    parquet_path      TEXT NOT NULL,
    vintage_quality   TEXT NOT NULL DEFAULT 'true_first_release',
    superseded_by     TEXT
);
-- DuckDB treats NULLs as distinct in UNIQUE indexes (ISO SQL behaviour).
-- Uniqueness of the (source, series, release_ts, revision_ts) tuple is
-- enforced by the PITWriter, not by this index. See
-- v2/pit_store/writer.py:_find_exact_slot.
"""

MANIFEST_COLUMNS = (
    "manifest_id",
    "source",
    "dataset",
    "series",
    "release_ts",
    "usable_after_ts",
    "revision_ts",
    "observation_start",
    "observation_end",
    "schema_hash",
    "row_count",
    "checksum",
    "ingest_ts",
    "provenance",
    "parquet_path",
    "vintage_quality",
    "superseded_by",
)

MANIFEST_SELECT = ", ".join(MANIFEST_COLUMNS)


@dataclass(frozen=True)
class ManifestRow:
    """One vintage's metadata.

    `series` is optional for single-series sources (e.g. a single-table
    release). `revision_ts` is NULL for first-release vintages; non-null
    on revisions. `superseded_by` is set on the older row when a
    replacement arrives.
    """

    manifest_id: str
    source: str
    dataset: str | None
    series: str | None
    release_ts: datetime
    usable_after_ts: datetime
    revision_ts: datetime | None
    observation_start: date | None
    observation_end: date | None
    schema_hash: str
    row_count: int
    checksum: str
    ingest_ts: datetime
    provenance: dict
    parquet_path: str
    vintage_quality: str
    superseded_by: str | None

    @classmethod
    def from_row(cls, row: tuple) -> ManifestRow:
        (
            manifest_id,
            source,
            dataset,
            series,
            release_ts,
            usable_after_ts,
            revision_ts,
            observation_start,
            observation_end,
            schema_hash,
            row_count,
            checksum,
            ingest_ts,
            provenance,
            parquet_path,
            vintage_quality,
            superseded_by,
        ) = row
        return cls(
            manifest_id=manifest_id,
            source=source,
            dataset=dataset,
            series=series,
            release_ts=_as_utc(release_ts),
            usable_after_ts=_as_utc(usable_after_ts if usable_after_ts is not None else release_ts),
            revision_ts=_as_utc(revision_ts) if revision_ts is not None else None,
            observation_start=observation_start,
            observation_end=observation_end,
            schema_hash=schema_hash,
            row_count=row_count,
            checksum=checksum,
            ingest_ts=_as_utc(ingest_ts),
            provenance=json.loads(provenance) if isinstance(provenance, str) else provenance,
            parquet_path=parquet_path,
            vintage_quality=coerce_vintage_quality(vintage_quality).value,
            superseded_by=superseded_by,
        )


class PITManifest:
    """Thin Python wrapper over the DuckDB-backed manifest.

    All datetimes are normalised to UTC before write; reads return UTC
    datetimes. The DuckDB connection is held open for the lifetime of
    the object; call `close()` (or use as a context manager) to release.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn
        self.conn.execute(MANIFEST_DDL)
        self._migrate_schema()

    @classmethod
    def open(cls, pit_root: Path) -> PITManifest:
        return open_manifest(pit_root)

    # -- context-manager helpers ----------------------------------------------

    def __enter__(self) -> PITManifest:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # -- insert / update -------------------------------------------------------

    def insert(self, row: ManifestRow) -> None:
        """Insert a vintage row. Uniqueness on (source, series, release_ts,
        revision_ts) is enforced by the DB; caller is responsible for
        detecting and handling revisions via `supersede()`.
        """
        self.conn.execute(
            """
            INSERT INTO pit_manifest (
                manifest_id, source, dataset, series, release_ts, usable_after_ts,
                revision_ts,
                observation_start, observation_end, schema_hash, row_count,
                checksum, ingest_ts, provenance, parquet_path, vintage_quality,
                superseded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                row.manifest_id,
                row.source,
                row.dataset,
                row.series,
                _to_utc_naive(row.release_ts),
                _to_utc_naive(row.usable_after_ts),
                _to_utc_naive(row.revision_ts) if row.revision_ts is not None else None,
                row.observation_start,
                row.observation_end,
                row.schema_hash,
                row.row_count,
                row.checksum,
                _to_utc_naive(row.ingest_ts),
                json.dumps(row.provenance, sort_keys=True, default=str),
                row.parquet_path,
                coerce_vintage_quality(row.vintage_quality).value,
                row.superseded_by,
            ],
        )

    def supersede(self, older_manifest_id: str, newer_manifest_id: str) -> None:
        """Mark `older_manifest_id` as superseded by `newer_manifest_id`."""
        self.conn.execute(
            "UPDATE pit_manifest SET superseded_by = ? WHERE manifest_id = ?",
            [newer_manifest_id, older_manifest_id],
        )

    # -- queries --------------------------------------------------------------

    def get(self, manifest_id: str) -> ManifestRow | None:
        row = self.conn.execute(
            f"SELECT {MANIFEST_SELECT} FROM pit_manifest WHERE manifest_id = ?",
            [manifest_id],
        ).fetchone()
        return ManifestRow.from_row(row) if row is not None else None

    def find_first_release(
        self,
        source: str,
        series: str | None,
        release_ts: datetime,
        dataset: str | None = None,
    ) -> ManifestRow | None:
        """Find the first-release row (revision_ts IS NULL) for a vintage slot."""
        row = self.conn.execute(
            f"""
            SELECT {MANIFEST_SELECT} FROM pit_manifest
            WHERE source = ?
              AND ((? IS NULL AND dataset IS NULL) OR dataset = ?)
              AND ((? IS NULL AND series IS NULL) OR series = ?)
              AND release_ts = ?
              AND revision_ts IS NULL
            """,
            [source, dataset, dataset, series, series, _to_utc_naive(release_ts)],
        ).fetchone()
        return ManifestRow.from_row(row) if row is not None else None

    def list_all(
        self, source: str | None = None, dataset: str | None = None
    ) -> list[ManifestRow]:
        clauses: list[str] = []
        params: list[str] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if dataset is not None:
            clauses.append("dataset = ?")
            params.append(dataset)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT {MANIFEST_SELECT} FROM pit_manifest
            {where}
            ORDER BY source, dataset, series, release_ts
            """,
            params,
        ).fetchall()
        return [ManifestRow.from_row(r) for r in rows]

    def _migrate_schema(self) -> None:
        """Add columns introduced after the original v2 PIT schema.

        Existing local stores were created before `dataset` and
        `vintage_quality`. Migration keeps them readable while new writes
        receive the stricter metadata.
        """
        columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info('pit_manifest')").fetchall()
        }
        if "dataset" not in columns:
            self.conn.execute("ALTER TABLE pit_manifest ADD COLUMN dataset TEXT")
        if "usable_after_ts" not in columns:
            self.conn.execute("ALTER TABLE pit_manifest ADD COLUMN usable_after_ts TIMESTAMP")
            self.conn.execute(
                "UPDATE pit_manifest SET usable_after_ts = release_ts "
                "WHERE usable_after_ts IS NULL"
            )
        if "vintage_quality" not in columns:
            self.conn.execute(
                "ALTER TABLE pit_manifest ADD COLUMN vintage_quality TEXT "
                "DEFAULT 'true_first_release'"
            )
            self.conn.execute(
                "UPDATE pit_manifest SET vintage_quality = 'true_first_release' "
                "WHERE vintage_quality IS NULL"
            )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS pit_manifest_lookup
                ON pit_manifest (source, dataset, series, release_ts)
            """
        )


def open_manifest(pit_root: Path) -> PITManifest:
    """Open (or create) the manifest at `pit_root/pit.duckdb`."""
    pit_root.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(pit_root / "pit.duckdb"))
    return PITManifest(conn)


# -- internal helpers ---------------------------------------------------------


def new_manifest_id() -> str:
    return f"mf_{uuid.uuid4().hex[:16]}"


def _to_utc_naive(ts: datetime) -> datetime:
    """DuckDB TIMESTAMP is timezone-naive. Normalise to UTC and drop tzinfo."""
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(UTC).replace(tzinfo=None)


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)
