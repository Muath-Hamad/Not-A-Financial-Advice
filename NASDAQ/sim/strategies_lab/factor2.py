"""factor2 — the multi-factor desk, drawdown-hardened.

WHAT THIS IS
------------
The alpha engine is `factor` unchanged: the same five orthogonal sleeves
(TREND / MOM_FAST / MOM_SLOW / LOWVOL / REVERSAL), the same robust
cross-sectional z-scores, the same conviction-tilted book with rank hysteresis,
the same sleeve-attribution adapt() that back-propagates realised trade P&L onto
the sleeve weights. Nothing in the selection logic has been touched, because the
selection logic was never the problem.

THE PROBLEM IT FIXES
--------------------
On the in-sample record (2016-2022) the parent had the field's best return and
its worst drawdown (-34.4%, peak 2019-12-26 -> trough 2020-03-16). The post-mortem
of that episode, and of the two other 30%-class holes in the same record
(2018-09 -> 2018-12, -29.8%; 2021-02 -> 2021-05, -32.2%), says the book was not
selecting badly — it was *de-risking a window late*:

  (a) the vol target was driven by the 21-day realised vol of the *holdings*,
      a backward-looking estimate that had barely moved by the time the index had
      already fallen 20%;
  (b) there was no same-session valve at all — target gross was only ever
      recomputed on the 5-session rebalance cadence;
  (c) the gross floor was 0.55, so even a full-alarm regime read left the book
      more than half invested;
  (d) the own-drawdown scaler only started to bite past -18% and bottomed at
      0.60, i.e. it responded after the damage rather than during it;
  (e) and the whole dial was only ever recomputed on the quarterly adapt()
      cadence and the weekly rebalance, so the crash response arrived late by
      construction.

THE GOVERNOR (grafted on; every device below was already proven in this arena)
-----------------------------------------------------------------------------
1. SAME-SESSION CIRCUIT BREAKER (the device from `regime`). An index air-pocket
   — IXIC ret_1d <= PANIC_RET — while participation is thin (breadth below
   PANIC_BREADTH) caps gross at PANIC_GROSS for PANIC_DAYS sessions and bars
   every new entry. It fires the session it triggers, on the close of the day
   itself, and it re-arms on every fresh air pocket, so a cascade keeps the lid
   on. Two conditions, not one: a -3% day inside a broad tape is noise; a -3%
   day with half the universe already under its 50-day line is a liquidation.

2. CONTINUOUS OWN-DRAWDOWN GOVERNOR (the device from `trend`). dd_scalar slides
   smoothly from 1.0 at DD_SOFT to DD_FLOOR at DD_HARD and slides back up on its
   own as equity recovers — no mode, no latch, nothing that can get stuck "off".
   The high-water reference itself BLEEDS PEAK_BLEED per session, so a stale peak
   can never suppress the book through an entire recovery (the trap that would
   otherwise cost more than the crash it avoided).

3. FAST VOL REACTION. The holdings-vol estimate is kept — it is the right *level*
   — but is multiplied by an index volatility ACCELERATION term: the 7-session
   realised vol of IXIC against its own slow EMA baseline. Acceleration is a
   ratio, so it is scale-free and regime-free: it says "the tape is three times
   more violent this week than it has been this quarter" in three days rather
   than in three weeks, which is exactly the lag that made (a) fatal.

4. GROSS FLOOR 0.55 -> 0.50, and made adaptive. Only a modest cut: the floor is
   a *steady-state* tax — it lowers the dial in every mediocre tape, not only in
   an alarm — and the alarm cutting is done by the three multiplicative caps
   above, which is where it belongs. Floors of 0.35 and 0.28 were both tested and
   both lost more to under-exposure in ordinary weather than they saved in
   crashes (see THE COST CURVE below).

5. FEAR-TIGHTENED TRAILS (the device from `defense`). A continuous fear read —
   index distance from its 52-week high, or thin breadth, whichever is worse,
   EMA-smoothed — contracts the ATR trail on every open position to FEAR_TRAIL x
   its resting width and arms it TRAIL_ARM_FEAR earlier. This one earns its keep:
   switching it off costs both axes at once.

6. THE VALVE IS SAME-SESSION, NOT CADENCED. Target gross is recomputed every
   session from live holdings; if the book is running more than RISK_BAND above
   what the governor allows, an off-cycle de-risk rebalance is forced that day.
   The ceiling is a RATCHET — it drops the session the governor says so and
   climbs back at most RERISK_STEP a session. Risk comes off at the speed of the
   tape and goes back on at the speed of conviction; without the ratchet the
   daily read sawtooths and the book pays the spread in both directions.

7. BOOK BREADTH as risk control: N_POS 10 -> 13, MAX_W 0.18 -> 0.13. This is the
   only lever found that buys drawdown WITHOUT buying cash drag — nothing is
   uninvested, there is simply no line big enough to decide a year on its own.
   Both are the parent's own adaptive parameters and adapt() still tunes them.

THE COST CURVE (why the governor is this size and not larger)
------------------------------------------------------------
This book's metric surface is chaotic: a 0.005% change to one threshold reshuffles
which names it holds and swings final equity ~35% and max drawdown ~2pp. Single
runs therefore cannot rank designs, and the parent's own record is one draw from
a wide distribution, not a fixed point. Every choice above was made on the median
of an ENSEMBLE of runs perturbed by economically meaningless amounts, and the
ensembles say something the single runs hide: past a point, cutting exposure
makes max drawdown WORSE. The metric is peak-to-trough over the whole record, so
a book that de-risks hard also recovers slowly, stays under water longer, and
meets the next shock on an unrecovered curve. Deep-cut variants (dd floor 0.30,
gross floor 0.28-0.35, hair-trigger breakers) all landed at -30% or worse while
giving up a third of the return. The governor is sized to stop the fall and then
get out of the way.

Tested and REJECTED, each on ensemble medians:
  * fear tilt of the sleeve blend toward LOWVOL — the obvious "protect without
    cash drag" idea, and wrong: median equity 350k -> 283k, median dd -26.5% ->
    -30.7%. Rotating a concentrated book under stress just sells the recovery.
  * high-water bleed gated on tape health (bleed only while the market itself is
    recovering) — sound in theory, -26.5% -> -31.1% and equity -20% in practice.
  * fear-scaled re-risk (rebuild faster once fear collapses) — -25.2% -> -26.9%.
  * gross-relative dust floor (scaling MIN_W with the gross target so a de-risk
    trims instead of liquidating) — costs both axes; the parent's absolute floor
    is better because full exits at least stop paying the loser.

Every governor parameter is in meta["param_space"] and is tuned by adapt() under
the same rules as the rest: deterministic, bounded, small steps, no lookahead.
adapt() tightens the governor after a window that took a >15% drawdown and
relaxes it after a clean one, so the insurance gets cheaper when it is not needed.

No dates, no per-ticker plans, no memorised tape. Deterministic, stdlib only,
no IO.
"""

from __future__ import annotations

import math

from strategy_base import Strategy

# ---------------------------------------------------------------- eligibility
LIQ_MIN = 20_000_000.0     # 20d EMA of dollar turnover — liquidity floor
LIQ_ALPHA = 0.10
LIQ_MIN_OBS = 5
PX_MIN = 5.0
ATR_LO, ATR_HI = 0.006, 0.12

# ---------------------------------------------------------------- portfolio
REBAL_EVERY = 5            # weekly cadence
CASH_TRIGGER = 0.20        # idle cash that forces an off-cycle rebalance
HOLD_MULT = 2.5            # keep a holding while inside top HOLD_MULT * N_POS
MIN_HOLD = 15              # sessions before a rank-based exit may fire
MAX_NEW = 5                # new names per rebalance (path smoothing)
MIN_W = 0.030
MAX_GROSS = 0.99
BAND = 0.030               # no-trade band on top-ups
TRIM_BAND = 0.060          # wider band on trims — never trim a winner for noise
MIN_TRADE = 2_000.0
CONV_TILT = 0.60           # linear rank tilt inside the book
IV_POW = 0.25              # inverse-vol sizing exponent (0 = equal, 1 = full)
IV_CLAMP = 0.30            # cap on the inverse-vol multiplier's deviation
SECTOR_FRAC = 0.55         # never more than half the slots in one sector
RHO = 0.55                 # assumed average pairwise correlation for vol target

# ---------------------------------------------------------------- exits
TRAIL_ARM = 0.25           # the trail arms only after a real run
VSCALE_FLOOR = 0.30

# ------------------------------------------------------------------ governor
VAR_SLOW_ALPHA = 0.02      # EMA on squared index returns (~3-month baseline)
VOL_FAST_N = 7             # short index realised-vol window (sessions)
VOL_ANN_FLOOR = 0.10       # annualised floor under the slow baseline
ACCEL_LO, ACCEL_HI = 0.70, 3.00
ACCEL_TRIG = 1.25          # acceleration below this is noise, not a crash
RISK_BAND = 0.10           # gross overshoot that forces an off-cycle de-risk
RERISK_STEP = 0.04         # how fast the gross ceiling may climb back per session
IX_TAPE = 90               # sessions of index returns kept in state
FEAR_DD_A, FEAR_DD_B = 0.05, 0.16     # index 52w drawdown magnitude ramp
FEAR_BR_A, FEAR_BR_B = 0.45, 0.20     # breadth ramp
FEAR_SMOOTH = 0.50
TRAIL_ARM_FEAR = 0.10      # the trail arms this much earlier at full fear

# ---------------------------------------------------------------- adapt
LR_SLEEVE = 0.22           # multiplicative step on sleeve weights
MIN_ATTRIB = 6             # closed trades needed before touching sleeve weights
HIT_TARGET = 0.45
PF_TARGET = 1.5
DD_BAD = -0.15             # window drawdown that tightens the governor
DD_OK = -0.07              # window drawdown that lets it breathe out again
DD_CUM_BAD = -0.20         # cumulative drawdown that tightens it harder

SLEEVES = ("W_TREND", "W_MOM_FAST", "W_MOM_SLOW", "W_LOWVOL", "W_REVERSAL")
_INF = float("inf")


def _ok(x):
    return isinstance(x, (int, float)) and x == x and -_INF < x < _INF


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _median(xs):
    n = len(xs)
    if n == 0:
        return 0.0
    s = sorted(xs)
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])


def _zmap(codes, vals):
    """Robust cross-sectional z (median / 1.4826*MAD), clipped to +/-3."""
    if not vals:
        return {}
    med = _median(vals)
    mad = _median([abs(v - med) for v in vals]) * 1.4826
    if mad <= 1e-12:
        n = len(vals)
        mu = sum(vals) / n
        var = sum((v - mu) ** 2 for v in vals) / max(1, n - 1)
        mad = math.sqrt(var)
    if mad <= 1e-12:
        return {c: 0.0 for c in codes}
    inv = 1.0 / mad
    return {c: _clamp((v - med) * inv, -3.0, 3.0) for c, v in zip(codes, vals)}


class FactorGuarded(Strategy):
    meta = {
        "handle": "factor2",
        "name": "Factor (guarded)",
        "style": ("Same five-sleeve cross-sectional factor engine as factor — trend quality, fast "
                  "and slow momentum, low volatility, short-term reversal — wrapped in a "
                  "drawdown governor: same-session index circuit breaker, continuous own-drawdown "
                  "scaler off a bleeding high-water mark, index vol-acceleration in the vol "
                  "target, and fear-tightened trails. adapt() back-propagates realised trade P&L "
                  "onto the sleeve weights and tunes the governor off realised drawdown."),
        "risk_style": "systematic multi-factor, vol-targeted, drawdown-governed",
        "color": "#888888",
        "param_space": {
            # --- alpha engine (unchanged from factor)
            "W_TREND": [0.05, 0.60],
            "W_MOM_FAST": [0.02, 0.50],
            "W_MOM_SLOW": [0.05, 0.60],
            "W_LOWVOL": [0.00, 0.40],
            "W_REVERSAL": [0.00, 0.45],
            "TARGET_VOL": [0.30, 0.62],
            "N_POS": [6.0, 14.0],
            "STOP_LOSS": [0.15, 0.35],
            "TRAIL_ATR": [4.0, 10.0],
            "MAX_W": [0.12, 0.26],
            # --- drawdown governor
            "GROSS_FLOOR": [0.22, 0.60],
            "PANIC_RET": [-0.045, -0.012],
            "PANIC_BREADTH": [0.30, 0.62],
            "PANIC_GROSS": [0.18, 0.60],
            "PANIC_DAYS": [2.0, 7.0],
            "DD_SOFT": [-0.14, -0.04],
            "DD_HARD": [-0.32, -0.14],
            "DD_FLOOR": [0.35, 0.80],
            "PEAK_BLEED": [0.0000, 0.0040],
            "VOL_FAST_W": [0.00, 0.90],
            "FEAR_TRAIL": [0.45, 1.00],
        },
    }

    def __init__(self):
        # adaptive parameters — every one bounded by meta["param_space"]
        self.p = {
            # --- alpha engine: factor's priors, except the two RISK priors below
            "W_TREND": 0.28,
            "W_MOM_FAST": 0.14,
            "W_MOM_SLOW": 0.28,
            "W_LOWVOL": 0.12,
            "W_REVERSAL": 0.22,
            "TARGET_VOL": 0.46,
            "N_POS": 13.0,           # 10 -> 13: breadth is drawdown control that
            "STOP_LOSS": 0.25,       # costs no cash drag, unlike cutting gross
            "TRAIL_ATR": 7.0,
            "MAX_W": 0.13,           # 0.18 -> 0.13: no single line decides a year
            # --- drawdown governor
            "GROSS_FLOOR": 0.50,     # was 0.55 — see note 4, a modest cut tested best
            "PANIC_RET": -0.025,     # index air-pocket that trips the breaker
            "PANIC_BREADTH": 0.50,   # ... only when participation is already thin
            "PANIC_GROSS": 0.32,     # gross cap while the breaker is live
            "PANIC_DAYS": 4.0,       # sessions the cap stays on after a trip
            "DD_SOFT": -0.06,        # own drawdown where de-risking starts
            "DD_HARD": -0.22,        # ... and where it is fully engaged
            "DD_FLOOR": 0.45,        # gross multiplier at full own-drawdown
            "PEAK_BLEED": 0.0015,    # high-water mark bleeds ~30%/yr toward equity
            "VOL_FAST_W": 0.50,      # weight on index vol acceleration
            "FEAR_TRAIL": 0.70,      # trail width at full fear
        }
        self._turn = {}        # code -> EMA of dollar turnover
        self._turn_n = {}      # code -> observations seen
        self._peak = {}        # code -> peak close since entry
        self._entry_z = {}     # code -> sleeve z-vector at entry (backprop input)
        self._entry_day = {}
        self._last_up = {}     # code -> last seen unrealised return
        self._held_prev = set()
        self._attrib = []      # closed-trade attribution since the last adapt()
        self._eq_peak = 0.0
        self._reg_bucket = None
        self._sent_prev = 0.0
        self._last_rebal = -99
        # --- governor state
        self._ixret = []       # causal tape of index 1d returns
        self._var_slow = None  # EMA of squared index returns (slow baseline)
        self._panic_until = -10 ** 9
        self._fear = 0.0
        self._last_est = None  # last usable book-vol estimate
        self._gross_cap = 1.0  # ratcheted gross ceiling: cuts now, rebuilds slowly

    # ------------------------------------------------------------- scoring
    def _score_universe(self, view):
        """Rank the eligible cross-section. Returns (ranked, zvecs)."""
        codes, rows = [], []
        for c, r in view.items():
            if c == "IXIC":
                continue
            if self._turn_n.get(c, 0) < LIQ_MIN_OBS or self._turn.get(c, 0.0) < LIQ_MIN:
                continue
            px = r.get("Close")
            if not _ok(px) or px < PX_MIN:
                continue
            ap = r.get("atr_pct")
            if not _ok(ap) or ap < ATR_LO or ap > ATR_HI:
                continue
            s50, s200, v21 = r.get("sma50"), r.get("sma200"), r.get("vol_21")
            r1w, r1d = r.get("ret_1w"), r.get("ret_1d")
            r1m, r3m, r6m, r12m = (r.get("ret_1m"), r.get("ret_3m"),
                                   r.get("ret_6m"), r.get("ret_12m"))
            rs = r.get("rs_bench_3m")
            vals = (s50, s200, v21, r1w, r1d, r1m, r3m, r6m, r12m, rs)
            bad = False
            for x in vals:
                if not _ok(x):
                    bad = True
                    break
            if bad or s50 <= 0 or s200 <= 0 or v21 <= 0:
                continue
            codes.append(c)
            rows.append((px, s50, s200, v21, ap, r1w, r1d, r1m, r3m, r6m, r12m, rs))
        if len(codes) < 15:
            return [], {}

        z_t1 = _zmap(codes, [t[1] / t[2] - 1.0 for t in rows])       # 50d vs 200d
        z_t2 = _zmap(codes, [t[0] / t[2] - 1.0 for t in rows])       # price vs 200d
        z_f1 = _zmap(codes, [t[8] for t in rows])                    # ret_3m
        z_f2 = _zmap(codes, [t[11] for t in rows])                   # rs_bench_3m
        z_s1 = _zmap(codes, [t[9] for t in rows])                    # ret_6m
        z_s2 = _zmap(codes, [t[10] - t[7] for t in rows])            # 12m less 1m
        z_v1 = _zmap(codes, [-t[3] for t in rows])                   # -vol_21
        z_v2 = _zmap(codes, [-t[4] for t in rows])                   # -atr_pct
        z_r1 = _zmap(codes, [-t[5] for t in rows])                   # -ret_1w
        z_r2 = _zmap(codes, [-t[6] for t in rows])                   # -ret_1d

        w = {k: max(0.0, float(self.p[k])) for k in SLEEVES}
        tot = sum(w.values())
        if tot <= 1e-9:
            w = {k: 1.0 / len(SLEEVES) for k in SLEEVES}
        else:
            w = {k: v / tot for k, v in w.items()}

        ranked, zvecs = [], {}
        for c, t in zip(codes, rows):
            zv = {
                "W_TREND": 0.5 * (z_t1[c] + z_t2[c]),
                "W_MOM_FAST": 0.5 * (z_f1[c] + z_f2[c]),
                "W_MOM_SLOW": 0.5 * (z_s1[c] + z_s2[c]),
                "W_LOWVOL": 0.5 * (z_v1[c] + z_v2[c]),
                "W_REVERSAL": 0.5 * (z_r1[c] + z_r2[c]),
            }
            zvecs[c] = zv
            ranked.append((sum(w[k] * zv[k] for k in SLEEVES), c, t))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        return ranked, zvecs

    # ------------------------------------------------------- vol acceleration
    def _vol_accel(self, ixr):
        """Ratio of short-window index realised vol to its own slow baseline.

        Scale-free by construction: it reads how much more violent this week is
        than this quarter, so it says the same thing in a 12-vol tape and a
        40-vol tape, and it says it within days instead of within a 21-day
        window. Causal — today's return is included, nothing beyond it.
        """
        s = ixr * ixr
        self._var_slow = s if self._var_slow is None else \
            self._var_slow + VAR_SLOW_ALPHA * (s - self._var_slow)
        tape = self._ixret
        if len(tape) < 4 or not _ok(self._var_slow):
            return 1.0
        n = min(VOL_FAST_N, len(tape))
        win = tape[-n:]
        v_fast = math.sqrt(252.0 * sum(x * x for x in win) / n)
        v_slow = math.sqrt(252.0 * max(self._var_slow, 1e-10))
        if not (_ok(v_fast) and _ok(v_slow)):
            return 1.0
        return _clamp(v_fast / max(v_slow, VOL_ANN_FLOOR), ACCEL_LO, ACCEL_HI)

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0))
        pos = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        eq = float(portfolio.get("equity", 0.0) or 0.0)
        if not _ok(eq) or eq <= 0:
            eq = 1.0
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = breadth if _ok(breadth) else 0.5
        sectors = ctx.get("sectors") or {}
        P = self.p

        # --- book-keeping: closed positions feed the back-propagation ledger
        held_now = set(pos)
        for c in self._held_prev - held_now:
            zv = self._entry_z.pop(c, None)
            up = self._last_up.pop(c, None)
            self._peak.pop(c, None)
            self._entry_day.pop(c, None)
            if zv is not None and _ok(up):
                self._attrib.append((float(up), zv))
        if len(self._attrib) > 400:
            self._attrib = self._attrib[-400:]
        self._held_prev = held_now

        # --- trailing liquidity state (causal EMA of dollar turnover)
        for c, r in view.items():
            if c == "IXIC":
                continue
            t = r.get("turnover_sar")
            if _ok(t) and t >= 0.0:
                prev = self._turn.get(c)
                self._turn[c] = t if prev is None else prev + LIQ_ALPHA * (t - prev)
                self._turn_n[c] = self._turn_n.get(c, 0) + 1

        # --- index tape (causal): 1d return, vol acceleration, fear read
        ix = view.get("IXIC") or {}
        ixr = ix.get("ret_1d")
        if not _ok(ixr):
            ixr = ctx.get("tasi_ret_1d", 0.0)
        ixr = _clamp(float(ixr), -0.5, 0.5) if _ok(ixr) else 0.0
        self._ixret.append(ixr)
        if len(self._ixret) > IX_TAPE:
            self._ixret = self._ixret[-IX_TAPE:]
        accel = self._vol_accel(ixr)

        i_d52 = ix.get("dist_52w_high")
        i_dd = abs(float(i_d52)) if (_ok(i_d52) and float(i_d52) < 0) else 0.0
        ramp_a = _clamp((i_dd - FEAR_DD_A) / (FEAR_DD_B - FEAR_DD_A), 0.0, 1.0)
        ramp_b = _clamp((FEAR_BR_A - breadth) / (FEAR_BR_A - FEAR_BR_B), 0.0, 1.0)
        raw_fear = ramp_a if ramp_a > ramp_b else ramp_b
        self._fear = (1.0 - FEAR_SMOOTH) * self._fear + FEAR_SMOOTH * raw_fear
        fear = _clamp(self._fear, 0.0, 1.0)

        # === GOVERNOR 1: same-session circuit breaker ========================
        # An index air pocket on thin participation. Two conditions, because a
        # -3% day inside a broad tape is noise and a -3% day with the universe
        # already under its 50-day line is a liquidation. Fires today, re-arms
        # on every fresh air pocket, decays by itself.
        tripped = (ixr <= float(P["PANIC_RET"])) and (breadth < float(P["PANIC_BREADTH"]))
        if tripped:
            self._panic_until = day + int(round(_clamp(P["PANIC_DAYS"], 1.0, 10.0)))
        panic = day <= self._panic_until

        # --- continuous regime dial (never a binary switch)
        ic, i200, i50 = ix.get("AdjClose"), ix.get("sma200"), ix.get("sma50")
        if _ok(ic) and _ok(i200) and i200 > 0:
            reg_t = _clamp((ic / i200 - 1.0 + 0.04) / 0.10, 0.0, 1.0)
        else:
            reg_t = 0.7
        if _ok(ic) and _ok(i50) and i50 > 0:
            reg_t = 0.75 * reg_t + 0.25 * _clamp((ic / i50 - 1.0 + 0.03) / 0.06, 0.0, 1.0)
        reg_b = _clamp((breadth - 0.30) / 0.35, 0.0, 1.0)
        health = 0.65 * reg_t + 0.35 * reg_b
        g_floor = _clamp(float(P["GROSS_FLOOR"]), 0.0, 1.0)
        regime = g_floor + (1.0 - g_floor) * health

        # === GOVERNOR 2: own drawdown off a BLEEDING high-water mark ==========
        # The reference decays toward equity every session, so a stale peak can
        # never keep the book small through an entire recovery — the trap that
        # otherwise costs more than the crash it avoided. Deliberately small: at
        # PEAK_BLEED a session the mark forgives roughly a third of a year's
        # distance annually, fast enough to let a recovering book back in and
        # slow enough that a real hole is still visible to the valve.
        bleed = _clamp(float(P["PEAK_BLEED"]), 0.0, 0.02)
        self._eq_peak = max(eq, self._eq_peak * (1.0 - bleed))
        own_dd = (eq / self._eq_peak - 1.0) if self._eq_peak > 0 else 0.0
        dd_soft = float(P["DD_SOFT"])
        dd_hard = min(float(P["DD_HARD"]), dd_soft - 0.02)
        if own_dd < dd_soft:
            span = dd_soft - dd_hard
            frac = _clamp((dd_soft - own_dd) / span, 0.0, 1.0) if span > 1e-9 else 1.0
            dd_scalar = _clamp(1.0 - frac * (1.0 - float(P["DD_FLOOR"])),
                               float(P["DD_FLOOR"]), 1.0)
        else:
            dd_scalar = 1.0

        # === GOVERNOR 6: the valve is checked EVERY session ===================
        # Live book vol from what is actually held (not from the next rebalance's
        # targets), so the allowed gross is known on any day, not just cadence
        # days. If the book is running above it, an off-cycle de-risk is forced.
        live_est = None
        if pos:
            wsum = 0.0
            vsum = 0.0
            for c, ph in pos.items():
                w_ = float(ph.get("weight", 0.0) or 0.0)
                r = view.get(c)
                v_ = r.get("vol_21") if r is not None else None
                v_ = float(v_) if (_ok(v_) and v_ > 0) else None
                if w_ > 0 and v_ is not None:
                    wsum += w_
                    vsum += w_ * max(0.10, v_)
            if wsum > 1e-9:
                k_ = max(1, len(pos))
                live_est = (vsum / wsum) * math.sqrt(RHO + (1.0 - RHO) / k_)
        if live_est is not None:
            self._last_est = live_est
        est_live = live_est if live_est is not None else self._last_est
        raw_live = self._gross_target(regime, est_live, accel, dd_scalar, panic)
        # RATCHET: the ceiling drops the session the governor says so, and climbs
        # back at most RERISK_STEP a session. Risk comes off at the speed of the
        # tape and goes back on at the speed of conviction — without this the
        # daily read sawtooths and the book pays the spread both ways.
        self._gross_cap = raw_live if raw_live < self._gross_cap else \
            min(raw_live, self._gross_cap + RERISK_STEP)
        gross_live = self._gross_cap
        cur_gross = 0.0
        for _, ph in pos.items():
            w_ = float(ph.get("weight", 0.0) or 0.0)
            if w_ > 0:
                cur_gross += w_

        orders, sells, notes = [], set(), []

        # ------------------------------------------------------ daily exits
        # === GOVERNOR 5: fear-tightened trails ===============================
        stop_loss = float(self.p["STOP_LOSS"])
        tscale = 1.0 - fear * (1.0 - _clamp(float(P["FEAR_TRAIL"]), 0.2, 1.0))
        trail_atr = float(self.p["TRAIL_ATR"]) * tscale
        arm = TRAIL_ARM - TRAIL_ARM_FEAR * fear
        for c, ph in pos.items():
            r = view.get(c)
            px = r.get("Close") if r is not None else None
            up = ph.get("unrealized_pct", 0.0)
            up = up if _ok(up) else 0.0
            self._last_up[c] = up
            if _ok(px):
                self._peak[c] = max(self._peak.get(c, px), px)
            pk = self._peak.get(c)
            atr = r.get("atr14") if r is not None else None
            s50 = r.get("sma50") if r is not None else None
            s200 = r.get("sma200") if r is not None else None
            reason = None
            if up <= -stop_loss:
                reason = f"disaster stop {up:+.1%}"
            elif (_ok(px) and _ok(pk) and _ok(atr) and atr > 0 and up >= arm
                  and px <= pk - trail_atr * atr):
                reason = (f"trail: {trail_atr:.1f}x ATR off the peak (fear {fear:.2f}), "
                          f"banked {up:+.1%}")
            elif (up < 0.0 and _ok(px) and _ok(s50) and _ok(s200)
                  and px < s50 and px < s200):
                reason = f"trend break under 50d and 200d at {up:+.1%}"
            if reason:
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sells.add(c)
                if abs(up) >= 0.30:
                    notes.append(f"{c} out at {up:+.0%} — {reason}")

        # ------------------------------------------------------- rebalance
        cash_frac = cash / eq if eq > 0 else 0.0
        risk_off = cur_gross > gross_live + RISK_BAND     # the same-session valve
        due = (day - self._last_rebal >= REBAL_EVERY) or \
              (cash_frac > CASH_TRIGGER and day - self._last_rebal >= 2) or \
              risk_off
        if due:
            ranked, zvecs = self._score_universe(view)
            if ranked:
                self._last_rebal = day
                n_pos = int(round(_clamp(self.p["N_POS"], 6.0, 14.0)))
                max_w = float(self.p["MAX_W"])
                rank_of = {c: i for i, (_, c, _) in enumerate(ranked)}
                keep_lim = int(round(HOLD_MULT * n_pos))

                # 1. surviving holdings: rank hysteresis + a minimum holding period
                targets = []
                for sc, c, t in ranked:
                    if len(targets) >= n_pos:
                        break
                    if c in pos and c not in sells:
                        young = (day - self._entry_day.get(c, day - 999)) < MIN_HOLD
                        if rank_of[c] < keep_lim or young:
                            targets.append((sc, c, t))
                # 2. fill the remaining slots from the top of the ranking.
                #    The breaker bars every NEW name while it is live: in an air
                #    pocket the cheapest risk control is to stop adding risk.
                new_n = 0
                sec_cap = max(3, int(SECTOR_FRAC * n_pos))
                sec_n = {}
                for _, c, _ in targets:
                    k_ = sectors.get(c, "Other")
                    sec_n[k_] = sec_n.get(k_, 0) + 1
                if len(targets) < n_pos and not panic:
                    have = {c for _, c, _ in targets}
                    for sc, c, t in ranked:
                        if len(targets) >= n_pos or new_n >= MAX_NEW:
                            break
                        if c in have or c in pos or c in sells:
                            continue
                        if not (t[0] > t[2]):      # entry gate: above its own 200d
                            continue
                        k_ = sectors.get(c, "Other")
                        if sec_n.get(k_, 0) >= sec_cap:   # no single-sector book
                            continue
                        sec_n[k_] = sec_n.get(k_, 0) + 1
                        targets.append((sc, c, t))
                        have.add(c)
                        new_n += 1

                # 3. conviction tilt + mild inverse-vol tilt
                k = len(targets)
                tgt = {}
                if k:
                    vbar = sum(max(0.10, float(t[3])) for _, _, t in targets) / k
                    raw = {}
                    for i, (sc, c, t) in enumerate(targets):
                        tilt = (1.0 + CONV_TILT * (1.0 - 2.0 * i / (k - 1))) if k > 1 else 1.0
                        iv = _clamp((vbar / max(0.10, float(t[3]))) ** IV_POW,
                                    1.0 - IV_CLAMP, 1.0 + IV_CLAMP)
                        raw[c] = max(1e-9, tilt * iv)
                    ssum = sum(raw.values())
                    base = {c: v / ssum for c, v in raw.items()}
                    # 4. vol target -> gross exposure, now through the governor
                    sig = sum(base[c] * max(0.10, float(t[3])) for _, c, t in targets)
                    est = sig * math.sqrt(RHO + (1.0 - RHO) / k)
                    if est > 1e-6:
                        self._last_est = est
                    gross = min(self._gross_target(regime, est if est > 1e-6 else est_live,
                                                   accel, dd_scalar, panic),
                                self._gross_cap)
                    tgt = {c: base[c] * gross for c in base}
                    # single-name cap, one redistribution pass
                    over = [c for c, w_ in tgt.items() if w_ > max_w]
                    if over:
                        spill = sum(tgt[c] - max_w for c in over)
                        rest = {c: w_ for c, w_ in tgt.items() if c not in over}
                        rsum = sum(rest.values())
                        for c in over:
                            tgt[c] = max_w
                        if rsum > 1e-9:
                            for c in rest:
                                tgt[c] = min(max_w, rest[c] + spill * rest[c] / rsum)
                    tgt = {c: w_ for c, w_ in tgt.items() if w_ >= MIN_W}

                # 5. sells first — the engine recycles that cash at the same open,
                #    so exits fund entries on the same fill. Positions are NOT
                #    rebalanced back down to their entry weight: a winner is
                #    allowed to become a bigger share of the book, and is only
                #    trimmed for a cap breach or to bring total gross to target.
                proceeds = 0.0
                gross_after = 0.0
                for c, ph in pos.items():
                    if c in sells:
                        proceeds += float(ph.get("value", 0.0) or 0.0)
                        continue
                    cw = float(ph.get("weight", 0.0) or 0.0)
                    if tgt.get(c, 0.0) <= 0.0:
                        orders.append({"code": c, "side": "sell", "all": True,
                                       "reason": "factor exit: out of the ranked book"})
                        sells.add(c)
                        proceeds += float(ph.get("value", 0.0) or 0.0)
                    else:
                        gross_after += cw
                gross_tgt = sum(tgt.values())
                for c, ph in pos.items():
                    if c in sells:
                        continue
                    cw = float(ph.get("weight", 0.0) or 0.0)
                    if cw <= 0:
                        continue
                    cut = 0.0
                    if cw > max_w * 1.15:
                        cut = cw - max_w
                    if gross_after > gross_tgt + TRIM_BAND:
                        cut = max(cut, cw * (gross_after - gross_tgt) / gross_after)
                    if cut * eq > MIN_TRADE and cut / cw > 0.08:
                        frac = _clamp(cut / cw, 0.0, 0.9)
                        why = "cap / gross target" if not panic else "circuit breaker"
                        orders.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                       "reason": f"trim {frac:.0%}: {why}"})
                        proceeds += cut * eq

                # 6. buys, best score first. While the breaker is live `targets`
                #    holds nothing but existing positions (step 2 was skipped), so
                #    the only buys that can happen are top-ups toward a weight the
                #    governor has already capped. New risk is barred; holding the
                #    surviving book at its allowed size is not the same thing, and
                #    liquidating to nothing is how a crash valve turns into a
                #    permanent loss of the recovery.
                avail = max(0.0, cash + proceeds * 0.995 - 200.0)
                for sc, c, t in targets:
                    tw = tgt.get(c, 0.0)
                    if tw <= 0.0 or avail < MIN_TRADE:
                        continue
                    cw = 0.0 if c in sells else float(pos.get(c, {}).get("weight", 0.0) or 0.0)
                    gap = tw - cw
                    if gap <= BAND or gap * eq < MIN_TRADE:
                        continue
                    amt = min(gap * eq, avail)
                    if amt < MIN_TRADE:
                        continue
                    orders.append({"code": c, "side": "buy", "sar": round(amt, 2),
                                   "reason": f"score {sc:+.2f}, rank {rank_of[c] + 1}, "
                                             f"target {tw:.1%}"})
                    avail -= amt
                    if c not in self._entry_z and c in zvecs:
                        self._entry_z[c] = zvecs[c]
                        self._entry_day[c] = day
                        px0 = t[0]
                        self._peak.setdefault(c, px0 if _ok(px0) else 0.0)

        # sells must be queued ahead of buys so they fill first at the next open
        orders.sort(key=lambda o: 0 if o["side"] == "sell" else 1)

        # ------------------------------------------------------- journal
        bucket = int(regime * 5)
        note = ""
        if tripped:
            note = (f"circuit breaker: IXIC {ixr:+.1%} on {breadth:.0%} breadth — gross capped "
                    f"at {float(P['PANIC_GROSS']):.0%} for {int(round(P['PANIC_DAYS']))} sessions, "
                    f"no new names")
        elif notes:
            note = notes[0]
        elif own_dd <= dd_soft and dd_scalar < 0.95 and day % 21 == 0:
            note = (f"drawdown governor at {own_dd:+.1%} off the high-water mark: gross "
                    f"multiplier {dd_scalar:.2f}, vol acceleration {accel:.2f}x")
        elif self._reg_bucket is not None and bucket != self._reg_bucket:
            note = (f"regime dial {regime:.2f} (IXIC trend {reg_t:.2f}, breadth {breadth:.0%}) "
                    f"— target gross moves with it")
        self._reg_bucket = bucket

        sent = _clamp(2.2 * (regime - 0.78) + 1.2 * (breadth - 0.5) + 4.0 * own_dd
                      - 0.6 * fear - (0.35 if panic else 0.0), -1.0, 1.0)
        sent = 0.5 * self._sent_prev + 0.5 * sent
        self._sent_prev = sent
        out = {"orders": orders, "sentiment": round(sent, 2)}
        if note:
            out["note"] = note
        return out

    # ---------------------------------------------------- the gross governor
    def _gross_target(self, regime, est, accel, dd_scalar, panic):
        """regime dial x vol target x own-drawdown scaler, capped by the breaker.

        GOVERNOR 3 lives here: the holdings-vol estimate sets the *level* and the
        index vol acceleration sets the *response speed*. est is inflated by
        VOL_FAST_W x (accel - 1), so a tape that has tripled its own realised vol
        inside a week halves the vol-target scale within days instead of waiting
        for a 21-day window to catch up.
        """
        P = self.p
        vscale = 1.0
        if est is not None and _ok(est) and est > 1e-6:
            # One-sided on purpose. Acceleration wobbles either side of 1.0 all
            # the time; charging the book for every wobble is a permanent tax on
            # exposure that costs far more over seven years than the crashes it
            # softens. Only ACCELERATION past ACCEL_TRIG — the tape genuinely
            # breaking out of its own recent range of violence — moves the dial.
            excess = accel - ACCEL_TRIG
            eff = est * (1.0 + _clamp(float(P["VOL_FAST_W"]), 0.0, 1.0) *
                         (excess if excess > 0.0 else 0.0))
            vscale = _clamp(float(P["TARGET_VOL"]) / eff, VSCALE_FLOOR, 1.0)
        gross = _clamp(regime * vscale, 0.0, 1.0) * dd_scalar * MAX_GROSS
        if panic:
            gross = min(gross, float(P["PANIC_GROSS"]))
        return _clamp(gross, 0.0, 1.0)

    # --------------------------------------------------------------- adapt
    def adapt(self, feedback):
        w = {}
        cum = {}
        if isinstance(feedback, dict):
            if isinstance(feedback.get("window"), dict):
                w = feedback["window"]
            if isinstance(feedback.get("cumulative"), dict):
                cum = feedback["cumulative"]
        space = self.meta["param_space"]
        before = dict(self.p)
        bits = []

        def step(name, d):
            lo, hi = space[name]
            self.p[name] = _clamp(self.p[name] + d, lo, hi)

        # --- 1. back-propagate realised P&L onto the sleeve weights ----------
        recs = self._attrib
        if len(recs) >= MIN_ATTRIB:
            n = len(recs)
            rbar = sum(r for r, _ in recs) / n
            cov = {}
            for k in SLEEVES:
                zb = sum(zv.get(k, 0.0) for _, zv in recs) / n
                cov[k] = sum((zv.get(k, 0.0) - zb) * (r - rbar) for r, zv in recs) / n
            scale = max(abs(v) for v in cov.values())
            if scale > 1e-12:
                for k in SLEEVES:
                    g = _clamp(cov[k] / scale, -1.0, 1.0)
                    lo, hi = space[k]
                    self.p[k] = _clamp(self.p[k] * math.exp(LR_SLEEVE * g), lo, hi)
                best = max(SLEEVES, key=lambda kk: cov[kk])
                worst = min(SLEEVES, key=lambda kk: cov[kk])
                bits.append(f"{n} closed trades: {best[2:].lower()} paid, "
                            f"{worst[2:].lower()} did not")
        self._attrib = []

        # --- 2. exposure follows realised Sharpe and drawdown ----------------
        sh, dd = w.get("sharpe"), w.get("max_dd")
        d_vol = 0.0
        if _ok(sh):
            if sh > 1.2:
                d_vol += 0.015
            elif sh < 0.2:
                d_vol -= 0.015
        if _ok(dd) and dd < -0.18:
            d_vol -= 0.015
        if d_vol:
            lo, hi = space["TARGET_VOL"]
            self.p["TARGET_VOL"] = _clamp(self.p["TARGET_VOL"] + d_vol, lo, hi)
            bits.append(f"vol target -> {self.p['TARGET_VOL']:.3f}")

        # --- 3. stop width follows hit rate ----------------------------------
        hr, pf = w.get("hit_rate"), w.get("profit_factor")
        if _ok(hr):
            lo, hi = space["STOP_LOSS"]
            if hr < HIT_TARGET - 0.10:
                self.p["STOP_LOSS"] = _clamp(self.p["STOP_LOSS"] + 0.015, lo, hi)
            elif hr > HIT_TARGET + 0.15 and (not _ok(pf) or pf < 1.2):
                self.p["STOP_LOSS"] = _clamp(self.p["STOP_LOSS"] - 0.015, lo, hi)

        # --- 4. trail width and book breadth follow profit factor ------------
        if _ok(pf):
            lo, hi = space["TRAIL_ATR"]
            if pf < PF_TARGET:
                self.p["TRAIL_ATR"] = _clamp(self.p["TRAIL_ATR"] + 0.35, lo, hi)
            elif pf > PF_TARGET + 1.0:
                self.p["TRAIL_ATR"] = _clamp(self.p["TRAIL_ATR"] - 0.20, lo, hi)
            lo, hi = space["N_POS"]
            if pf < 1.0:
                self.p["N_POS"] = _clamp(self.p["N_POS"] + 0.5, lo, hi)
            elif pf > 2.0:
                self.p["N_POS"] = _clamp(self.p["N_POS"] - 0.5, lo, hi)
            lo, hi = space["MAX_W"]
            if pf > 2.0:
                self.p["MAX_W"] = _clamp(self.p["MAX_W"] + 0.01, lo, hi)
            elif pf < 1.0:
                self.p["MAX_W"] = _clamp(self.p["MAX_W"] - 0.01, lo, hi)

        # --- 5. the governor follows realised drawdown -----------------------
        # Insurance that was needed gets tightened; insurance that was not needed
        # gets cheaper. Same rules as everything else: small, bounded, one-sided
        # per window, deterministic.
        tighten = _ok(dd) and dd <= DD_BAD
        relax = _ok(dd) and dd >= DD_OK and (not _ok(sh) or sh > 0.0)
        if tighten:
            step("PANIC_RET", 0.0015)       # trips on a shallower air pocket
            step("PANIC_BREADTH", 0.010)    # ... at a less extreme breadth read
            step("PANIC_GROSS", -0.020)
            step("PANIC_DAYS", 0.25)
            step("DD_SOFT", 0.005)          # the ramp engages earlier
            step("DD_HARD", 0.005)
            step("DD_FLOOR", -0.020)
            step("VOL_FAST_W", 0.040)
            step("GROSS_FLOOR", -0.015)
            step("FEAR_TRAIL", -0.025)
            bits.append(f"window dd {dd:+.1%}: governor tightened")
        elif relax:
            step("PANIC_RET", -0.0010)
            step("PANIC_BREADTH", -0.008)
            step("PANIC_GROSS", 0.015)
            step("PANIC_DAYS", -0.25)
            step("DD_SOFT", -0.004)
            step("DD_HARD", -0.004)
            step("DD_FLOOR", 0.015)
            step("VOL_FAST_W", -0.025)
            step("GROSS_FLOOR", 0.010)
            step("FEAR_TRAIL", 0.020)
            bits.append(f"window dd {dd:+.1%}: governor eased")
        cdd = cum.get("dd_from_peak")
        if _ok(cdd) and cdd <= DD_CUM_BAD:
            step("DD_FLOOR", -0.015)
            step("PEAK_BLEED", 0.0002)      # dig out faster once the hole is deep
            step("VOL_FAST_W", 0.020)
        elif _ok(cdd) and cdd > -0.05:
            step("PEAK_BLEED", -0.0001)
        # keep the ramp ordered whatever the steps did
        if self.p["DD_HARD"] > self.p["DD_SOFT"] - 0.04:
            lo, hi = space["DD_HARD"]
            self.p["DD_HARD"] = _clamp(self.p["DD_SOFT"] - 0.04, lo, hi)

        changes = {k: round(v, 4) for k, v in self.p.items()
                   if abs(v - before.get(k, v)) > 1e-9}
        ret, br = w.get("ret"), w.get("bench_ret")
        head = f"window {ret:+.1%} vs IXIC {br:+.1%}. " if (_ok(ret) and _ok(br)) else ""
        note = head + ("; ".join(bits) if bits else "no usable gradient, parameters held")
        return {"changes": changes, "note": note[:300]}


STRATEGY = FactorGuarded()
