"""Thin CLI shim for the v2 public-data ingest layer.

Two subcommands:

* ``backfill --source <name>`` — instantiate the named ingester with
  default arguments and call ``.ingest()``.
* ``build-features --grid {daily,weekly} --start <iso> --end <iso>
  [--output <path>]`` — call
  :func:`v2.ingest.public_feature_join.build_features`.

Operator runbook: ``docs/v2/operator_runbook_public_data.md``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from v2.ingest._secrets import MissingAPIKeyError
from v2.ingest.public_feature_join import build_features
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

DEFAULT_PIT_ROOT = Path("data/pit_store")
DEFAULT_FEATURE_DIR = Path("data/public/feature_sets")

SOURCE_KEYS = (
    "eia",
    "eia_wpsr_archive",
    "fred",
    "cftc_cot",
    "wti_prices",
    "baker_hughes",
    "cme_cl_metadata",
    "cboe_vix",
    "fomc_calendar",
    "eia_steo_calendar",
    "eia_steo_value_archive",
    "opec_ministerial_calendar",
    "eia_psm_calendar",
    "gpr_calendar",
    "cl_front_eod_pit",
    "brent_front_eod_pit",
    "rbob_front_eod_pit",
    "ng_front_eod_pit",
)


def _build_ingester(
    source_key: str,
    writer: PITWriter,
    manifest,
    *,
    since: str | None = None,
    until: str | None = None,
):
    """Wire a source key to its ingester with default arguments.

    Imports are lazy so that a missing optional API key (FRED/EIA) only
    surfaces an actionable error when that source is actually invoked.
    """
    if source_key == "eia":
        from v2.ingest.eia_wpsr import EIAWPSRIngester

        return EIAWPSRIngester(writer=writer, manifest=manifest)
    if source_key == "eia_wpsr_archive":
        from datetime import date

        from v2.ingest.eia_wpsr_archive import EIAWPSRArchiveIngester

        return EIAWPSRArchiveIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "fred":
        from v2.ingest.fred_alfred import FREDAlfredIngester

        return FREDAlfredIngester(writer=writer, manifest=manifest)
    if source_key == "cftc_cot":
        from datetime import UTC

        from v2.ingest.cftc_cot import CFTCCOTIngester

        if since is None:
            years = None
        else:
            start_year = datetime.fromisoformat(since).replace(tzinfo=UTC).year
            current_year = datetime.now(UTC).year
            years = list(range(start_year, current_year + 1))
        return CFTCCOTIngester(writer=writer, manifest=manifest, years=years)
    if source_key == "wti_prices":
        from v2.ingest.wti_prices import WTIPricesIngester

        return WTIPricesIngester(writer=writer, manifest=manifest)
    if source_key == "baker_hughes":
        from v2.ingest.baker_hughes_rig_count import BakerHughesIngester

        return BakerHughesIngester(writer=writer, manifest=manifest)
    if source_key == "cme_cl_metadata":
        from v2.ingest.cme_contract_metadata_public import CMEContractMetadataIngester

        return CMEContractMetadataIngester(writer=writer, manifest=manifest)
    if source_key == "cboe_vix":
        from v2.ingest.cboe_vix import CboeVIXIngester

        return CboeVIXIngester(writer=writer, manifest=manifest)
    if source_key == "fomc_calendar":
        from datetime import date

        from v2.ingest.fomc_calendar import FOMCCalendarIngester

        return FOMCCalendarIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "eia_steo_calendar":
        from datetime import date

        from v2.ingest.eia_steo_calendar import EIASTEOCalendarIngester

        return EIASTEOCalendarIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "eia_steo_value_archive":
        from datetime import date

        from v2.ingest.eia_steo_value_archive import EIASTEOValueArchiveIngester

        return EIASTEOValueArchiveIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "opec_ministerial_calendar":
        from datetime import date

        from v2.ingest.opec_ministerial_calendar import (
            OPECMinisterialCalendarIngester,
        )

        return OPECMinisterialCalendarIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "eia_psm_calendar":
        from datetime import date

        from v2.ingest.eia_psm_calendar import EIAPSMCalendarIngester

        return EIAPSMCalendarIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "gpr_calendar":
        from datetime import date

        from v2.ingest.gpr_calendar import GPRCalendarIngester

        return GPRCalendarIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "cl_front_eod_pit":
        from datetime import date

        from v2.ingest.cl_front_eod_pit import CLFrontEODPITIngester

        return CLFrontEODPITIngester(
            writer=writer,
            manifest=manifest,
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "brent_front_eod_pit":
        from datetime import date

        from v2.ingest.stooq_multi_asset import StooqMultiAssetIngester

        return StooqMultiAssetIngester(
            writer=writer,
            manifest=manifest,
            asset="brent",
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "rbob_front_eod_pit":
        from datetime import date

        from v2.ingest.stooq_multi_asset import StooqMultiAssetIngester

        return StooqMultiAssetIngester(
            writer=writer,
            manifest=manifest,
            asset="rbob",
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    if source_key == "ng_front_eod_pit":
        from datetime import date

        from v2.ingest.stooq_multi_asset import StooqMultiAssetIngester

        return StooqMultiAssetIngester(
            writer=writer,
            manifest=manifest,
            asset="ng",
            since=date.fromisoformat(since) if since is not None else None,
            until=date.fromisoformat(until) if until is not None else None,
        )
    raise ValueError(f"unknown source key: {source_key!r}")


def _cmd_backfill(args: argparse.Namespace) -> int:
    pit_root = Path(args.pit_root)
    pit_root.mkdir(parents=True, exist_ok=True)
    manifest = open_manifest(pit_root)
    writer = PITWriter(pit_root, manifest)
    try:
        ingester = _build_ingester(
            args.source,
            writer,
            manifest,
            since=args.since,
            until=args.until,
        )
        try:
            results = ingester.ingest()
        except MissingAPIKeyError as e:
            print(
                f"error: missing API key for source {args.source!r}: {e}\n"
                "see docs/v2/operator_runbook_public_data.md for the env-var setup.",
                file=sys.stderr,
            )
            return 2
        print(f"ingested {len(results)} vintages from {args.source!r}")
        return 0
    finally:
        manifest.close()


def _cmd_build_features(args: argparse.Namespace) -> int:
    pit_root = Path(args.pit_root)
    manifest = open_manifest(pit_root)
    reader = PITReader(pit_root, manifest)
    try:
        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end)
        if args.output is not None:
            output = Path(args.output)
        else:
            output = DEFAULT_FEATURE_DIR / f"wti_public_features_{args.grid}.parquet"
        df = build_features(
            manifest=manifest,
            reader=reader,
            grid=args.grid,
            start=start,
            end=end,
            output_path=output,
        )
        print(f"wrote {len(df)} rows x {len(df.columns)} cols to {output}")
        return 0
    finally:
        manifest.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m v2.ingest.cli",
        description="v2 public-data ingest CLI (backfill + feature-join shim).",
    )
    p.add_argument(
        "--pit-root",
        default=str(DEFAULT_PIT_ROOT),
        help=f"PIT store root (default: {DEFAULT_PIT_ROOT})",
    )
    sub = p.add_subparsers(dest="command", required=True)

    bf = sub.add_parser("backfill", help="run an ingester with default args")
    bf.add_argument("--source", required=True, choices=SOURCE_KEYS)
    bf.add_argument(
        "--since",
        default=None,
        help=(
            "optional ISO date lower bound where supported; currently used "
            "to bound CFTC annual backfill years and WPSR archive issues"
        ),
    )
    bf.add_argument(
        "--until",
        default=None,
        help="optional ISO date upper bound where supported",
    )
    bf.set_defaults(func=_cmd_backfill)

    feats = sub.add_parser("build-features", help="build the PIT-safe feature join")
    feats.add_argument("--grid", required=True, choices=("daily", "weekly"))
    feats.add_argument("--start", required=True, help="ISO datetime")
    feats.add_argument("--end", required=True, help="ISO datetime")
    feats.add_argument("--output", default=None, help="output parquet path")
    feats.set_defaults(func=_cmd_build_features)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
