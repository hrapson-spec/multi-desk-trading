"""Point-in-time feature store.

Governed by docs/v2/v2_data_contract.md (hash in docs/v2/hashes/).

Layout:
    manifest         -- DuckDB-backed bitemporal manifest table.
    writer           -- Ingest raw Parquet vintages + record manifest row.
    reader           -- as_of / latest_available_before / vintage_diff queries.
    release_calendar -- Per-source YAML loader + PIT-eligibility predicate.
"""

from v2.pit_store.manifest import ManifestRow, PITManifest, open_manifest
from v2.pit_store.reader import PITChecksumError, PITReader, ReadResult
from v2.pit_store.release_calendar import ReleaseCalendar, load_calendar, load_calendars_dir
from v2.pit_store.writer import PITWriter

__all__ = [
    "ManifestRow",
    "PITChecksumError",
    "PITManifest",
    "PITReader",
    "PITWriter",
    "ReadResult",
    "ReleaseCalendar",
    "load_calendar",
    "load_calendars_dir",
    "open_manifest",
]
