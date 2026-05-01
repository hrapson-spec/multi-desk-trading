"""Scheduler contract tests.

Real ingesters aren't implemented yet; we exercise the scheduler with
stub ingesters to pin the isolation and error-handling invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from v2.ingest.base import BaseIngester, FetchResult
from v2.ingest.scheduler import IngestScheduler
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter


class StubIngester(BaseIngester):
    name = "stub_src"
    source = "stub_src"

    def __init__(self, writer, manifest, rows: int = 2):
        super().__init__(writer, manifest)
        self._rows = rows

    def fetch(self, as_of_ts=None):
        return [
            FetchResult(
                source="stub_src",
                series="main",
                release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
                revision_ts=None,
                data=pd.DataFrame({"value": [1.0] * self._rows}),
                provenance={"source": "stub", "method": "mem"},
            )
        ]


class FailingIngester(BaseIngester):
    name = "fail_src"
    source = "fail_src"

    def fetch(self, as_of_ts=None):
        raise RuntimeError("synthetic")


def test_scheduler_runs_and_collects(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    sched = IngestScheduler()
    sched.register(StubIngester(w, m))
    report = sched.run(datetime(2026, 1, 14, 21, 0, tzinfo=UTC))
    assert report.success_count == 1
    assert report.error_count == 0
    assert "stub_src" in report.per_source_success
    m.close()


def test_scheduler_isolates_failures(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    sched = IngestScheduler()
    sched.register(FailingIngester(w, m))
    sched.register(StubIngester(w, m))
    report = sched.run(datetime(2026, 1, 14, 21, 0, tzinfo=UTC))
    assert report.success_count == 1
    assert report.error_count == 1
    assert "fail_src" in report.per_source_error
    assert "stub_src" in report.per_source_success
    m.close()


def test_disabled_ingester_is_skipped(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    sched = IngestScheduler()
    sched.register(FailingIngester(w, m), enabled=False)
    report = sched.run(datetime(2026, 1, 14, 21, 0, tzinfo=UTC))
    assert report.success_count == 0
    assert report.error_count == 0
    m.close()


def test_eia_ingester_instantiates_without_api_key(tmp_path, monkeypatch):
    """B2b: EIA ingester (and the other public-data ingesters) must be
    instantiable without an API key so they can be registered with the
    scheduler in environments without secrets (dry-run audits, CI).
    The key is resolved lazily on first ``fetch()`` call.
    """
    from v2.ingest.eia_wpsr import EIAWPSRIngester

    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(tmp_path / "no_such_config.yaml"))
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = EIAWPSRIngester(w, m, series_ids=["WCESTUS1"])
    assert ing.source == "eia"
    assert isinstance(ing, BaseIngester)
    m.close()
