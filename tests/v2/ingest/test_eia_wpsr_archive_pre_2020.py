"""Tier 2.A — pre-2020 WPSR backfill scaffold test.

Per the data-acquisition plan, pre-2020 WPSR backfill is a robustness
lever, not a Phase 3 gate-mover (the §9 phase gates are post-2020-only).
v1.0 does not perform live pre-2020 backfill; this test verifies that
the existing ``eia_wpsr_archive`` URL-bounds logic accepts pre-2020
dates without rejection so that a future operator-runbook step can
safely run:

    python -m v2.ingest.cli backfill --source eia_wpsr_archive \\
        --since 2003-01-01 --until 2019-12-31

Per spec v1 §11 forbidden #3, the resulting manifest rows must be
reported separately from post-2020 in the tractability output. The
v1 harness already supports pre/post-2020 separation via the
``post_2020_start`` parameter at
``feasibility/tractability_v1.py``.

Known-issue (v1.1 work): EIA WPSR archive HTML format changed at
least once around 2010 (table CSV link patterns, header structures).
The current parser at ``parse_issue_csv_links`` and
``extract_mapping_value`` may need date-range-conditional branches
when actually running against pre-2010 issues. The pre-2010 case is
NOT covered by v1.0 tests because the v2 fixture suite uses 2024
issue HTML only; live-fetching pre-2010 HTML is out of scope here.
"""

from __future__ import annotations

from datetime import date

from v2.ingest.eia_wpsr_archive import _url_date_in_bounds


def test_pre_2020_url_accepted_when_in_range():
    """The url-bounds filter must admit pre-2020 issue URLs."""
    url_2003 = (
        "https://www.eia.gov/petroleum/supply/weekly/archive/2003/"
        "2003_06_20/wpsr_2003_06_20.php"
    )
    assert _url_date_in_bounds(
        url_2003, since=date(2003, 1, 1), until=date(2019, 12, 31)
    )


def test_pre_2010_url_admitted_for_robustness_backfill():
    """2008 financial-crisis issue must pass the bounds filter."""
    url_2008 = (
        "https://www.eia.gov/petroleum/supply/weekly/archive/2008/"
        "2008_09_19/wpsr_2008_09_19.php"
    )
    # Run a backfill spanning the GFC week
    assert _url_date_in_bounds(
        url_2008, since=date(2008, 1, 1), until=date(2008, 12, 31)
    )


def test_post_2020_url_rejected_when_until_is_pre_2020():
    """A 2020 URL must be rejected when until=2019-12-31."""
    url_2020 = (
        "https://www.eia.gov/petroleum/supply/weekly/archive/2020/"
        "2020_06_24/wpsr_2020_06_24.php"
    )
    assert not _url_date_in_bounds(
        url_2020, since=date(2003, 1, 1), until=date(2019, 12, 31)
    )


def test_url_with_unparseable_date_passes_through():
    """A URL without a parseable date returns True (pass through)."""
    assert _url_date_in_bounds(
        "https://www.eia.gov/petroleum/supply/weekly/archive/index.html",
        since=date(2003, 1, 1),
        until=date(2019, 12, 31),
    )
