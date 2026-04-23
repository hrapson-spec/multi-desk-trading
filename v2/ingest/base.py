"""Ingester protocol + base class."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

import pandas as pd

from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter, WriteResult


@dataclass(frozen=True)
class FetchResult:
    """One vintage fetched from a publisher.

    `data` is the raw DataFrame; `release_ts` is the publisher's claimed
    release timestamp; `provenance` must contain at least {source, method,
    scraper_version}. A single fetch may return multiple vintages if the
    publisher exposes a batch (e.g. an ALFRED vintage range); in that
    case the ingester returns a list of FetchResult.
    """

    source: str
    series: str | None
    release_ts: datetime
    revision_ts: datetime | None
    data: pd.DataFrame
    provenance: dict
    observation_start: date | None = None
    observation_end: date | None = None


@runtime_checkable
class Ingester(Protocol):
    """Ingester contract.

    An ingester is named, knows which source it produces, and has a
    `fetch` method returning one or more FetchResult. The default
    `ingest` method (below) wraps PITWriter.write_vintage.
    """

    name: str
    source: str

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]: ...


class BaseIngester:
    """Concrete base class with a default ingest() method."""

    name: str = ""
    source: str = ""

    def __init__(self, writer: PITWriter, manifest: PITManifest):
        self.writer = writer
        self.manifest = manifest

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        raise NotImplementedError(
            f"{type(self).__name__}.fetch is not implemented at v2.0; "
            "provide a concrete network-fetching implementation before "
            "promoting this ingester past the Layer-1 PIT audit."
        )

    def ingest(self, as_of_ts: datetime | None = None) -> list[WriteResult]:
        results: list[WriteResult] = []
        for f in self.fetch(as_of_ts):
            r = self.writer.write_vintage(
                source=f.source,
                series=f.series,
                release_ts=f.release_ts,
                data=f.data,
                provenance=f.provenance,
                revision_ts=f.revision_ts,
                observation_start=f.observation_start,
                observation_end=f.observation_end,
            )
            results.append(r)
        return results
