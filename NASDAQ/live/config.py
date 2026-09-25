"""Central configuration for the live (paper) deployment of the elected agent.

Everything the live harness does is parameterized here — one file to read to
know what the system will and will not do. Changing any value is a
change-management event (docs/05 §7.4): commit it, and if it can alter
decisions, prove it with a regression first.
"""

import os
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]   # NASDAQ/
LIVE = PKG / "live"
# LIVE_LEDGER_DIR redirects every ledger write (tests and local drills use a
# scratch directory; a private deployment points it at its own ledger repo).
LEDGER = Path(os.environ.get("LIVE_LEDGER_DIR") or (LIVE / "ledger"))

# --- identity -------------------------------------------------------------
AGENT_HANDLE = "trend"
AGENT_FILE = PKG / "sim" / "strategies" / "trend.py"   # frozen file
FREEZE_COMMIT = "7e8cdf12f1a63e6e23f691ff1f01e580ca946acf"

# --- the live run ---------------------------------------------------------
# First session of the live record. The twin replays from here, so the model
# and a fresh account both start in cash on this day. Reset it (repository
# variable LIVE_START, or this default) at each phase switch: the first ghost
# session, then the first paper session. 2026-08-18 was the original ghost
# start; the schedules never fired from it (docs/07).
LIVE_START = os.environ.get("LIVE_START") or "2026-09-28"
START_CASH = 100_000.0
TIMEZONE = "America/New_York"

# --- twin cost model (venue actuals: Alpaca paper is commission-free; -----
# --- slippage stays modeled at 5 bps until Cycle B measures the real one) -
TWIN_COMMISSION = "0.0"
TWIN_SLIPPAGE = "0.0005"
ADAPT_EVERY = "63"           # same quarterly back-propagation cadence as the sims

# --- data -----------------------------------------------------------------
RAW_SUBDIR = "data/raw_live"          # refetched in full every Cycle A
ENRICHED_SUBDIR = "data/enriched_live"
FETCH_START = "2015-01-01"            # 200-day indicator warm-up depth

# --- data gate (docs/05 §3, Cycle A step 2) -------------------------------
GATE_CROSS_TOL = 0.005       # any cross-source close disagreeing > 0.5% trips
GATE_COVERAGE_MIN = 0.95     # fraction of ok names that must have a bar at asof
GATE_FETCH_OK_MIN = 0.90     # fraction of the universe that must fetch at all
GATE_XCHECK_MAX = 40         # symbols cross-checked against the second source

# --- ghost gate (docs/05 §10 Phase 1) -------------------------------------
GATE_TARGET_STREAK = 10      # consecutive dual-replay byte-matches to pass

# --- harness guardrails, enforced outside the agent (docs/05 §7.2) --------
MAX_POS_WEIGHT = 0.18        # per-name cap (trend's own sizing tops out ~13%)
MAX_DAILY_TURNOVER = 0.75    # sum of today's order values / equity
ADV_CAP = 0.05               # order value <= 5% of the name's 20d avg $ volume
KILL_DD_LIMIT = -0.25        # automatic kill-switch drawdown (docs/05 §7.1)

# --- order submission (docs/07; Alpaca's on-open window) ------------------
# Alpaca accepts market/limit-on-open (time_in_force "opg") orders only after
# 19:00 ET and before 09:28 ET; anything sent in between is rejected. Cycle A
# decides at 17:00 ET, a separate submit step sends the ledgered orders.
SUBMIT_OPENS_ET = (19, 0)    # earliest submission, ET
SUBMIT_CUTOFF_ET = (9, 28)   # Alpaca's last acceptance time before the open
SUBMIT_DEADLINE_ET = 21      # dead-man: a paper submission must be recorded by this hour
CASH_BUFFER = 0.002          # keep this share of equity uninvested after a night's buys
# Books diverging by more than this share of equity at submission time means
# the account and the twin do not describe the same portfolio (for example a
# LIVE_START that was not reset at the paper switch): submit nothing, P1.
START_MISMATCH_MAX = 0.20

# --- reconciliation & quality thresholds ----------------------------------
OPEN_REVISION_TOL = 0.002    # 09:50 open vs same-evening open, noted above this
TRACKING_ERROR_MONTHLY = 0.005  # paper-vs-twin alert threshold (Phase 2)
SLIPPAGE_ALERT = 0.0010      # average realized slippage per side above this -> P2
# Twin-vs-account share drift per name: whole-share order estimates from the
# prior close make small differences normal. Beyond both limits -> P1.
DRIFT_SHARES_TOL = 2
DRIFT_PCT_TOL = 0.05

# --- alerting -------------------------------------------------------------
P1_LABEL = "live-p1"
DEADMAN_DEADLINE_ET = 18     # Cycle A must have recorded by this ET hour

# --- broker (Phase 2; dormant in ghost mode) ------------------------------
ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets"
