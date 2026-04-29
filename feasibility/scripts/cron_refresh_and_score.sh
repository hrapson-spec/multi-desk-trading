#!/bin/bash
# Daily forward-pipeline driver: refresh WTI proxy, then score+resolve any due events.
#
# Designed for invocation by macOS launchd (see
# feasibility/scripts/launchd/com.henri.mdt.forward.plist) but is
# safe to run by hand for ad-hoc refresh.
#
# The wrapper is intentionally minimal:
#   1. cd to the repo (paths are absolute so working directory matters)
#   2. refresh_wti_spot_proxy.py — pulls FRED DCOILWTICO and atomically
#      replaces data/s4_0/free_source/raw/DCOILWTICO.csv. Writes status
#      to feasibility/forward/wti_lag_1d/wti_spot_refresh_status.json.
#   3. forward_wti_lag_1d.py — scores any due forecasts AND resolves
#      any outcomes whose target prices are now available. Idempotent
#      by design (lock-pinned forecast ledger).
#
# Failure semantics:
#   - The refresh step is allowed to fail (set +e around it). The
#     forward script has its own freshness gating (cf915d0
#     "gate forward scoring on fresh WTI proxy") and will skip events
#     whose required feature anchor is too stale.
#   - Any error from the forward script (e.g. lock integrity failure)
#     is fatal — exit non-zero so launchd's stderr log surfaces it.
#
# Logs land in feasibility/forward/wti_lag_1d/launchd_logs/ (created
# by launchd from the plist's StandardOutPath / StandardErrorPath).

set -euo pipefail

REPO_ROOT="/Users/henrirapson/projects/multi-desk-trading"
cd "$REPO_ROOT"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

echo "[$(ts)] cron_refresh_and_score.sh start"

# --- 1. Refresh WTI spot proxy (allowed to fail; forward gates on freshness) ---
echo "[$(ts)] refresh_wti_spot_proxy.py begin"
set +e
.venv/bin/python feasibility/scripts/refresh_wti_spot_proxy.py
refresh_rc=$?
set -e
if [ "$refresh_rc" -ne 0 ]; then
  echo "[$(ts)] WARN: refresh failed (rc=$refresh_rc); forward will gate on freshness"
else
  echo "[$(ts)] refresh ok"
fi

# --- 2. Score due events + resolve any outcomes whose prices are available ---
echo "[$(ts)] forward_wti_lag_1d.py begin"
.venv/bin/python feasibility/scripts/forward_wti_lag_1d.py
echo "[$(ts)] forward ok"

echo "[$(ts)] cron_refresh_and_score.sh done"
