# Forward Pipeline Automation (macOS launchd)

This runbook explains how to automate the daily refresh-score-resolve
loop for the WTI lag 1d forward holdout. After install, the pipeline
runs unattended once per day; outcomes accumulate without manual
intervention.

## What gets automated

A single shell wrapper at
`feasibility/scripts/cron_refresh_and_score.sh` runs two steps in
sequence:

1. **Refresh**: pull DCOILWTICO from FRED, atomically replace
   `data/s4_0/free_source/raw/DCOILWTICO.csv`, and update
   `feasibility/forward/wti_lag_1d/wti_spot_refresh_status.json`
   with the latest valid date and feature age. The forward script
   gates on this freshness, so refresh failures are tolerated and
   logged as warnings — the next step still runs.
2. **Score + resolve**: invoke `forward_wti_lag_1d.py` which:
   - Verifies the lock-integrity contract
     (`feasibility/forward/wti_lag_1d/lock.json` SHA-pins all
     load-bearing files; any drift refuses to score).
   - Scores any forecasts whose `decision_ts` has arrived since the
     last run.
   - Resolves outcomes for any prior forecasts whose target prices
     are now available in the freshly-refreshed CSV.
   - Writes structured logs to:
     - `forecasts.jsonl` — append-only forecast ledger
     - `outcomes.csv` — append-only outcome ledger
     - `forecast_chain.jsonl` — tamper-evident hash chain
     - `monitor_report.md` — human-readable status

The wrapper is idempotent. Running it multiple times in one day
produces no duplicate forecasts (event_id deduplication enforced by
the forward script).

## Schedule

Daily at **22:30 system-local time** (`StartCalendarInterval` Hour=22,
Minute=30 in the plist). The system-local timezone on this machine
is BST/GMT, so:

- 22:30 BST → 17:30 ET (EDT) → 21:30 UTC
- 22:30 GMT → 17:30 ET (EST) → 22:30 UTC

Both fall comfortably after FRED's typical evening DCOILWTICO refresh
(~6pm ET) regardless of US daylight savings. To change the schedule,
edit `Hour` / `Minute` in the plist and reload.

## Install

```bash
# 1. Copy the plist to the user LaunchAgents directory
cp feasibility/scripts/launchd/com.henri.mdt.forward.plist \
   ~/Library/LaunchAgents/

# 2. Bootstrap the agent into the user's launchd domain
launchctl bootstrap gui/$(id -u) \
   ~/Library/LaunchAgents/com.henri.mdt.forward.plist

# 3. Enable (in case macOS marks new agents disabled-by-default)
launchctl enable gui/$(id -u)/com.henri.mdt.forward

# 4. (Optional) Trigger one immediate run to verify
launchctl kickstart -p gui/$(id -u)/com.henri.mdt.forward

# 5. Verify status
launchctl print gui/$(id -u)/com.henri.mdt.forward | head -40
```

After step 4, check the logs:

```bash
tail -F feasibility/forward/wti_lag_1d/launchd_logs/stdout.log
tail -F feasibility/forward/wti_lag_1d/launchd_logs/stderr.log
```

## Verify a successful run

A clean run leaves these traces:

```bash
# Refresh status moved forward
cat feasibility/forward/wti_lag_1d/wti_spot_refresh_status.json | python3 -m json.tool
# Expected: status=refreshed, age_days <= 4

# Forecasts grew (or stayed equal if no event was due)
wc -l feasibility/forward/wti_lag_1d/forecasts.jsonl

# Outcomes grew if any prior forecast resolved
wc -l feasibility/forward/wti_lag_1d/outcomes.csv

# Monitor report timestamp advanced
head -3 feasibility/forward/wti_lag_1d/monitor_report.md
```

## Daily check (manual)

A 30-second human review:

```bash
cd /Users/henrirapson/projects/multi-desk-trading
tail -20 feasibility/forward/wti_lag_1d/monitor_report.md
```

The monitor report shows: forecasts scored, outcomes resolved,
running directional accuracy, gain vs zero-return baseline, gain vs
majority baseline, and the next 10 queued events. Promotion review
unblocks at 60 scored-and-resolved events.

## Failure modes and recovery

| Symptom | Likely cause | Action |
|---|---|---|
| `wti_spot_refresh_status.json` has `status=failed` for ≥3 days | FRED endpoint-level outage OR script-side regression | Probe FRED directly; check User-Agent isn't being overridden (see commit `55c223b` for prior CDN-sinkhole gotcha) |
| `LockIntegrityError` in stderr.log | A tracked file was modified after the lock was tagged | Either revert the change OR re-lock via `feasibility/scripts/lock_wti_lag_1d.py` (the latter weakens the integrity guarantee — document the rationale) |
| `forecasts.jsonl` stops growing despite events being due | Feature freshness gate triggered (proxy stale) OR launchd not running | Check `launchctl print gui/$(id -u)/com.henri.mdt.forward` and `wti_spot_refresh_status.json` |
| Permission denied on log files | macOS sandbox restriction on launchd output paths | Verify the log directory exists and is owned by the user; `launchd_logs/` should be `chmod 755` |

## Uninstall

```bash
launchctl bootout gui/$(id -u)/com.henri.mdt.forward
rm ~/Library/LaunchAgents/com.henri.mdt.forward.plist
```

The forward ledger files (`forecasts.jsonl`, `outcomes.csv`,
`forecast_chain.jsonl`) persist after uninstall. They are
append-only by design.

## Caveats

1. **Sleep / closed laptop**: launchd does NOT wake the system from
   sleep. If the machine is asleep at 22:30 local, the scheduled run
   fires when the system next wakes. Missed runs do not stack — the
   pipeline is idempotent and the next run catches up on outcomes
   whose target prices have since landed.
2. **Repo-path dependency**: the plist hardcodes
   `/Users/henrirapson/projects/multi-desk-trading`. If you move the
   repo, update the plist and reload.
3. **venv-path dependency**: the wrapper uses `.venv/bin/python` from
   the repo root. If you recreate the venv, the wrapper continues to
   work as long as `.venv/bin/python` exists.
4. **Promotion guard is OUT of this automation**: this loop scores
   and resolves; promotion review is a separate gated decision (60
   scored+resolved events, unchanged files, unchanged thresholds,
   explicit zero-return AND majority-baseline checks) and remains
   operator-driven.
