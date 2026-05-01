"""v2 ingestion layer.

Each ingester has two public methods:
    fetch(...) -> FetchResult
        Network call that returns a raw DataFrame + provenance. Never
        touches the PIT store. Unit-testable without the writer.
    ingest(...) -> list[WriteResult]
        Calls fetch, then PITWriter.write_vintage. Idempotent across runs
        thanks to the writer's checksum-aware re-ingest semantics.

Real network implementations for eia_wpsr, cftc_cot, fred_alfred, and
wti_prices are deferred past this commit. The Ingester protocol + dry-run
audit skeleton lands first so downstream code (scheduler, pit_audit)
has a stable interface to compile against.
"""

from v2.ingest.base import FetchResult, Ingester
from v2.ingest.scheduler import IngestScheduler, ScheduledIngester

__all__ = [
    "FetchResult",
    "IngestScheduler",
    "Ingester",
    "ScheduledIngester",
]
