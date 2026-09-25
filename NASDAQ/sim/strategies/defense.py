"""defense — adaptive defense desk on the AAOIFI-screened NASDAQ universe.

Thesis
------
On an exchange with a strong secular uptrend and violent, short corrections the
expensive mistake is *not being invested*. Every mechanism that answers a
falling tape by raising cash is an insurance premium paid every quiet quarter
for a payout that arrives twice a decade — and, worse, it is reliably still
switched off when the turn comes. So this book stays near-fully invested and
buys its defense in the two places that cost nothing while the tape is fine:

  1. WHAT IT OWNS — a liquidity test that survives a non-stationary tape, a
     trend-intactness requirement (above the 50- and 100-day, positive 6m/12m
     return, inside a bounded distance of the 52-week high), a wide 11-name
     book with sector caps, and volatility-scaled position sizes. A name that
     stops being a trend stops being owned.
  2. WHEN IT LEAVES — a volatility-scaled trailing stop that is WIDE by default
     (winners need room to compound) and contracts CONTINUOUSLY as market fear
     rises, plus a fast, small hard stop so a thesis that was simply wrong is
     cheap. Asymmetry, not prediction.

Cash is a residue, never a target: when few names clear the entry gates, slots
go unfilled. Every market-wide read in this file is a RAMP, not a switch — the
one mechanism the previous arena proved most reliably destroyed by regime
change was the binary regime gate.

THE RULEBOOK
------------
1. LIQUIDITY (dual test, re-derived every session, never a fixed list)
   A smoothed dollar-turnover EMA (alpha 1/20, >= 10 observations) must clear
   EITHER an absolute $10M floor OR 30% of the cross-sectional median. Dollar
   turnover on this market grows by an order of magnitude across a decade: a
   purely absolute floor empties the universe in early years, a purely relative
   one dumps good names whenever the whole tape goes quiet. Either-or is stable
   in both directions. Price floor $5, ATR% in [0.4%, 9%].

2. SCORE — a rank blend, never a formula on raw numbers. Five percentile ranks
   across the eligible cross-section: volatility-adjusted medium-term momentum
   (3m/6m, weight W_MT), volatility-adjusted long-term momentum (12m, W_LT),
   relative strength vs the composite (W_RS), proximity to the 52-week high
   (W_TQ — trend *quality*, not just trend size) and low realised volatility
   (W_LV). Percentile ranks are immune to outliers and to the level drift that
   breaks raw-value thresholds out of sample. A parabolic last month is
   penalised rather than banned.

3. ENTRY GATES (structural, all must hold): inside the top ENTRY_POOL of the
   ranking, above sma50 AND sma100, 6m (or 12m) return positive, within
   MAX_OFF_HIGH of the 52-week high, today's dollar turnover >= $3M, sector
   count under SECTOR_CAP, and not inside a post-exit cooldown. At most 3 new
   names a session (5 while rebuilding a badly under-invested book).

4. BOOK — 11 slots at 1/11 scaled by TARGET_ATR/ATR% (clamped 0.6x-1.5x), hard
   cap MAX_W with a trim back to TRIM_TO, 5 names per sector, gross target
   TARGET_GROSS. Volatility-scaled sizing leaves the book structurally under
   its gross target once every slot is taken, so a top-up rule adds to the
   single best-ranked healthy holding rather than letting cash pile up by
   accident. Being 90% invested instead of 96% is not prudence, it is a leak.

5. EXITS
   - hard stop at HARD_STOP off average cost — small, fast, unarguable;
   - trailing stop from the peak close since entry at
       clamp(TRAIL_K x ATR%, TRAIL_LO, TRAIL_HI) x fear_scale x brake_scale
     where fear_scale slides continuously from 1.0 down to FEAR_SCALE as the
     index 52-week drawdown deepens (-5% -> -16%) or breadth collapses (45% ->
     20%). Wide leash in a calm tape, short leash in a falling one, no step;
   - structural break: four consecutive closes below the 100-day;
   - liquidity failure: the name has left the tradeable band;
   - rank decay: three consecutive sessions outside slot + RANK_BUFFER, at most
     2 rotations a session — hysteresis, so nothing is sold for slipping a place.

6. ESCALATING OWN-DRAWDOWN BRAKES, measured against an equity high-water mark
   that bleeds ~0.08%/session so a stale peak can never brake the book through
   an entire recovery:
   - the ladder is CONTINUOUS. Exposure multiplier slides 1.0 -> DD_FLOOR as
     drawdown runs from DD_L1 to DD_L3, and it unwinds by itself as equity
     recovers. Entries throttle 3 -> 2 -> 1 a session over the same range and
     trails tighten with it. Nothing here can get stuck "off";
   - when gross runs more than DERISK_BAND above its braked target, the
     WEAKEST-RANKED lines are cut back — defense is paid for by the worst
     holdings, not the best;
   - level 3 (dd <= DD_L3) is the catastrophe step: gross to GROSS_L3 at once,
     an 8-session entry pause, and a 126-session refractory so it can fire at
     most twice a year. Throttled to 60%, never switched off;
   - a -5.5% own day pauses new entries for 2 sessions.

7. BACK-PROPAGATION — adapt(), every 63 sessions, deterministic and bounded:
   - realised drawdown (a smoothed |window max_dd|) against a DD_TARGET the
     book is built for drives TRAIL_K / TRAIL_HI / FEAR_SCALE and the whole
     DD_L1/L2/L3 ladder: deeper than target tightens, shallower widens, and
     the tightening step is larger than the loosening step. adapt() only moves
     the RESTING width — the live crash response is the fear ramp in decide(),
     which reacts the same session, so the two must not both chase the tape;
   - exit asymmetry from the hit-rate/profit-factor pair: winning often for
     little (high hit rate, thin profit factor) means the trail is cutting
     compounders early, so it widens; losing on both counts tightens the hard
     stop so the losses get smaller and faster;
   - gross exposure tracks a smoothed realised Sharpe, and is pushed up when a
     window badly under-participated in a rising benchmark while running light;
   - the rank buffer widens when realised turnover runs hot;
   - the momentum-horizon weights (W_MT vs W_LT) move toward whichever
     horizon's entry-time percentile rank actually predicted the sign of the
     realised P&L in the window, using attribution recorded at entry.
   Every update is a small step, clamped into meta["param_space"], with the
   brake ladder re-ordered afterwards so it can never invert, and reported in
   {"changes": ..., "note": ...} for audit.

No dates, no per-ticker plans, no memorised tape. Deterministic, stdlib only,
no file or network IO, NaN-guarded on every read.
"""

from __future__ import annotations

BENCH = "IXIC"

# --- liquidity / universe (structure, not adapted) -------------------------
LIQ_ALPHA = 1.0 / 20.0
LIQ_MIN_OBS = 10
LIQ_ABS = 10_000_000.0        # absolute dollar-turnover floor
LIQ_REL = 0.30                # ...or this fraction of the market median
LIQ_EXIT_ABS = 0.35           # holding drops out below this fraction of entry bar
PRICE_FLOOR = 5.0
ATR_MAX = 0.09
ATR_MIN = 0.004
TURN_TODAY_MIN = 3_000_000.0

# --- book shape ------------------------------------------------------------
N_SLOTS = 11
TARGET_W = 1.0 / N_SLOTS
MAX_W = 0.175
TRIM_TO = 0.140
SECTOR_CAP = 5
TARGET_ATR = 0.025
SIZE_LO, SIZE_HI = 0.60, 1.50
MIN_TICKET = 2_500.0
CASH_BUFFER = 0.985
MAX_ENTRIES = 3
REBUILD_ENTRIES = 5           # when the book is far under target, refill faster
REBUILD_GAP = 0.25            # ...meaning gross is this far below its target
TOPUP_GAP = 0.02              # add to the best holding when gross lags its target
MAX_ROTATIONS = 2
REORDER_GAP = 4               # sessions before a sold name may be re-bought
STOP_COOL = 8                 # longer cooldown after a stop/break exit
ORDER_GUARD = 3               # sessions before re-queuing the same code

# --- score weights (W_MT / W_LT adapted) -----------------------------------
W_RS = 0.80
W_TQ = 1.00
W_LV = 0.20
SPIKE_1M = 0.30
SPIKE_PEN = 0.35

# --- exits -----------------------------------------------------------------
BREAK_DAYS = 4
RANK_DECAY_DAYS = 3
TRAIL_FLOOR = 0.06

# --- fear ramp (continuous, never binary) ----------------------------------
FEAR_DD_A, FEAR_DD_B = 0.05, 0.16        # index 52w drawdown magnitude
FEAR_BR_A, FEAR_BR_B = 0.45, 0.20        # breadth
FEAR_SMOOTH = 0.50
FEAR_GROSS = 0.18            # max fraction of gross target given up at full fear
FEAR_POOL = 0.45             # entry pool narrows this much at full fear
FEAR_OFFHI = 0.35            # 52w-high window narrows this much at full fear

# --- brakes ----------------------------------------------------------------
PEAK_BLEED = 0.0008
DD_FLOOR = 0.55               # exposure multiplier at the deepest brake level
DERISK_BAND = 0.06            # gross must exceed target by this before trimming
DERISK_MAX = 2                # lines de-risked per session
GROSS_L3 = 0.60
L3_REFRACTORY = 126
L3_PAUSE = 8
DAYLOSS = -0.055
DAYLOSS_COOL = 2

# --- adapt -----------------------------------------------------------------
DD_TARGET = 0.10              # per-63-session window drawdown the book is built for
ATTR_MIN_N = 6


def _ok(x) -> bool:
    try:
        return x is not None and x == x and -1e17 < float(x) < 1e17
    except Exception:
        return False


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _pct_ranks(vals):
    """Percentile rank in [0,1] for each element, deterministic on ties."""
    n = len(vals)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: (vals[i], i))
    out = [0.0] * n
    d = float(n - 1)
    for r, i in enumerate(order):
        out[i] = r / d
    return out


try:
    from strategy_base import Strategy
except Exception:  # pragma: no cover - defensive import for odd loaders
    class Strategy:  # type: ignore
        meta = {}

        def decide(self, date, view, portfolio, ctx):
            raise NotImplementedError

        def adapt(self, feedback):
            return None


class Defense(Strategy):
    meta = {
        "handle": "defense",
        "name": "Defense",
        "style": ("Near-fully invested wide-book trend ownership: defense lives in "
                  "liquidity and trend-intactness screens, fear-scaled trailing "
                  "exits and a continuous own-drawdown brake ladder, never in cash."),
        "risk_style": "adaptive defense",
        "color": "#888888",
        "param_space": {
            "TRAIL_K": [5.0, 13.0],
            "TRAIL_LO": [0.09, 0.22],
            "TRAIL_HI": [0.18, 0.38],
            "FEAR_SCALE": [0.30, 0.85],
            "HARD_STOP": [-0.22, -0.08],
            "DD_L1": [-0.20, -0.05],
            "DD_L2": [-0.30, -0.10],
            "DD_L3": [-0.42, -0.18],
            "TARGET_GROSS": [0.80, 0.99],
            "ENTRY_POOL": [14.0, 45.0],
            "RANK_BUFFER": [6.0, 40.0],
            "MAX_OFF_HIGH": [0.16, 0.40],
            "W_MT": [0.50, 3.20],
            "W_LT": [0.30, 2.50],
        },
    }

    # ---------------------------------------------------------------- init
    def __init__(self):
        # adaptable parameters (defaults are deliberately round numbers)
        self.TRAIL_K = 8.0
        self.TRAIL_LO = 0.15
        self.TRAIL_HI = 0.30
        self.FEAR_SCALE = 0.45
        self.HARD_STOP = -0.12
        self.DD_L1 = -0.12
        self.DD_L2 = -0.19
        self.DD_L3 = -0.30
        self.TARGET_GROSS = 0.96
        self.ENTRY_POOL = 25.0
        self.RANK_BUFFER = 18.0
        self.MAX_OFF_HIGH = 0.28
        self.W_MT = 2.00
        self.W_LT = 1.00

        # state
        self._turn = {}          # code -> EMA of dollar turnover
        self._turn_n = {}        # code -> observation count
        self._med = 0.0          # cached cross-sectional median turnover EMA
        self._peak = {}          # code -> peak AdjClose since entry
        self._brk = {}           # code -> consecutive closes below sma200
        self._rkbad = {}         # code -> consecutive sessions outside the buffer
        self._cool = {}          # code -> day until re-entry barred
        self._ordered = {}       # code -> day an order was queued
        self._feat = {}          # code -> (p_mt, p_lt) at entry
        self._attr = []          # closed-trade attribution since last adapt
        self._eq_peak = 0.0
        self._fear = 0.0
        self._brake = 0
        self._l3_until = -1
        self._no_buy_until = -1
        self._dd_ema = DD_TARGET
        self._sh_ema = 0.0
        self._sent = 0.0
        self._n_adapt = 0

    # ------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0) or 0)
        pos = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        eq = portfolio.get("equity", 0.0)
        eq = float(eq) if _ok(eq) and float(eq) > 0 else max(1.0, cash)
        sectors = ctx.get("sectors") or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = float(breadth) if _ok(breadth) else 0.5
        hist = ctx.get("equity_history") or [eq]
        own_1d = 0.0
        if len(hist) >= 2 and _ok(hist[-1]) and _ok(hist[-2]) and hist[-2]:
            own_1d = hist[-1] / hist[-2] - 1.0

        # ---- own drawdown on a slowly bleeding high-water mark
        if self._eq_peak <= 0:
            self._eq_peak = eq
        self._eq_peak = max(eq, self._eq_peak * (1.0 - PEAK_BLEED))
        dd = eq / self._eq_peak - 1.0 if self._eq_peak > 0 else 0.0

        # ---- liquidity state (causal EMA of dollar turnover)
        tn, tc = self._turn, self._turn_n
        for c, r in view.items():
            if c == BENCH:
                continue
            t = r.get("turnover_sar")
            if _ok(t) and t > 0.0:
                p = tn.get(c)
                tn[c] = t if p is None else p + LIQ_ALPHA * (t - p)
                tc[c] = tc.get(c, 0) + 1
        if self._med <= 0.0 or day % 3 == 0:
            vals = sorted(v for c, v in tn.items()
                          if c in view and tc.get(c, 0) >= LIQ_MIN_OBS)
            self._med = vals[len(vals) // 2] if vals else 0.0
        med = self._med

        # ---- continuous fear read (index drawdown / breadth), never a switch
        idx = view.get(BENCH) or {}
        i_d52 = idx.get("dist_52w_high")
        i_dd = abs(float(i_d52)) if _ok(i_d52) and float(i_d52) < 0 else 0.0
        ramp_a = _clamp((i_dd - FEAR_DD_A) / (FEAR_DD_B - FEAR_DD_A), 0.0, 1.0)
        ramp_b = _clamp((FEAR_BR_A - breadth) / (FEAR_BR_A - FEAR_BR_B), 0.0, 1.0)
        raw_fear = ramp_a if ramp_a > ramp_b else ramp_b
        self._fear = (1.0 - FEAR_SMOOTH) * self._fear + FEAR_SMOOTH * raw_fear
        fear = _clamp(self._fear, 0.0, 1.0)

        # ---- cross-sectional ranking
        codes, rows = [], {}
        f_mt, f_lt, f_rs, f_tq, f_lv, f_sp = [], [], [], [], [], []
        for c, r in view.items():
            if c == BENCH:
                continue
            px = r.get("AdjClose")
            if not _ok(px) or float(px) < PRICE_FLOOR:
                continue
            te = tn.get(c)
            if te is None or tc.get(c, 0) < LIQ_MIN_OBS:
                continue
            if not (te >= LIQ_ABS or (med > 0.0 and te >= LIQ_REL * med)):
                continue
            ap = r.get("atr_pct")
            if not _ok(ap) or not (ATR_MIN <= float(ap) <= ATR_MAX):
                continue
            r3, r6, r12 = r.get("ret_3m"), r.get("ret_6m"), r.get("ret_12m")
            if not _ok(r3) or not _ok(r6):
                continue
            v21 = r.get("vol_21")
            v21 = float(v21) if _ok(v21) and float(v21) > 0.02 else 0.35
            vden = v21 if v21 > 0.18 else 0.18
            lt = float(r12) if _ok(r12) else float(r6)
            d52 = r.get("dist_52w_high")
            d52 = float(d52) if _ok(d52) else -0.60
            rs = r.get("rs_bench_3m")
            rs = float(rs) if _ok(rs) else 0.0
            r1m = r.get("ret_1m")
            codes.append(c)
            rows[c] = r
            f_mt.append((0.5 * float(r3) + 0.5 * float(r6)) / vden)
            f_lt.append(lt / vden)
            f_rs.append(rs)
            f_tq.append(d52)
            f_lv.append(-v21)
            f_sp.append(1.0 if (_ok(r1m) and float(r1m) > SPIKE_1M) else 0.0)

        p_mt = _pct_ranks(f_mt)
        p_lt = _pct_ranks(f_lt)
        p_rs = _pct_ranks(f_rs)
        p_tq = _pct_ranks(f_tq)
        p_lv = _pct_ranks(f_lv)
        scored = []
        for i, c in enumerate(codes):
            s = (self.W_MT * p_mt[i] + self.W_LT * p_lt[i] + W_RS * p_rs[i]
                 + W_TQ * p_tq[i] + W_LV * p_lv[i] - SPIKE_PEN * f_sp[i])
            scored.append((-s, c, i))
        scored.sort()
        rank = {}
        for k, (_s, c, _i) in enumerate(scored):
            rank[c] = k + 1

        # ---- escalating own-drawdown brake, applied CONTINUOUSLY.
        # A binary "stand down" switch is the single most expensive construction
        # in this arena: it is always still off when the turn comes. So the
        # ladder scales exposure instead of cutting it, and unwinds by itself as
        # equity recovers — no dwell timers, no state that can get stuck.
        span = (self.DD_L1 - self.DD_L3)
        prog = 0.0 if span <= 0 else _clamp((self.DD_L1 - dd) / span, 0.0, 1.0)
        dd_scale = 1.0 - prog * (1.0 - DD_FLOOR)
        prev_brake = self._brake
        self._brake = 2 if dd <= self.DD_L2 else (1 if dd <= self.DD_L1 else 0)
        if own_1d <= DAYLOSS:
            self._no_buy_until = max(self._no_buy_until, day + DAYLOSS_COOL)

        tscale = 1.0 - fear * (1.0 - self.FEAR_SCALE)
        tscale *= 0.85 + 0.15 * dd_scale
        eff_gross = self.TARGET_GROSS * dd_scale * (1.0 - FEAR_GROSS * fear)

        orders, sold, events = [], set(), []
        trimmed = set()
        rotations = 0
        buf = int(round(self.RANK_BUFFER))

        # ------------------------------------------------------------ exits
        for c, ph in pos.items():
            r = view.get(c)
            if r is None:
                continue
            px = r.get("AdjClose")
            up = ph.get("unrealized_pct", 0.0)
            up = float(up) if _ok(up) else 0.0
            if _ok(px):
                px = float(px)
                pk = self._peak.get(c)
                pk = px if pk is None else (px if px > pk else pk)
                self._peak[c] = pk
            else:
                px, pk = None, self._peak.get(c)
            ap = r.get("atr_pct")
            ap = float(ap) if _ok(ap) and float(ap) > 0 else TARGET_ATR
            trail = _clamp(self.TRAIL_K * ap, self.TRAIL_LO, self.TRAIL_HI) * tscale
            if trail < TRAIL_FLOOR:
                trail = TRAIL_FLOOR

            smid = r.get("sma100")
            if not _ok(smid):
                smid = r.get("sma200")
            if _ok(smid) and px is not None and px < float(smid):
                self._brk[c] = self._brk.get(c, 0) + 1
            else:
                self._brk[c] = 0
            rk = rank.get(c)
            if rk is None or rk > N_SLOTS + buf:
                self._rkbad[c] = self._rkbad.get(c, 0) + 1
            else:
                self._rkbad[c] = 0

            te = tn.get(c)
            liq_dead = (te is not None and te < LIQ_EXIT_ABS * LIQ_ABS
                        and (med <= 0 or te < LIQ_EXIT_ABS * LIQ_REL * med))

            reason = hard = None
            if up <= self.HARD_STOP:
                reason = "hard stop at %+.1f%% — wrong, not early" % (up * 100.0)
                hard = True
            elif self._brk[c] >= BREAK_DAYS:
                reason = ("trend break: %d closes under the 100-day, %+.1f%% on the line"
                          % (self._brk[c], up * 100.0))
                hard = True
            elif px is not None and pk and px <= pk * (1.0 - trail):
                reason = ("trail %.0f%% (fear %.2f) from peak %.2f -> %.2f, banked %+.1f%%"
                          % (trail * 100.0, fear, pk, px, up * 100.0))
                hard = True
            elif liq_dead:
                reason = "liquidity gone — the name left the tradeable band"
                hard = True
            elif self._rkbad.get(c, 0) >= RANK_DECAY_DAYS and rotations < MAX_ROTATIONS:
                reason = ("rank decay: outside slot+%d for %d sessions, rotating"
                          % (buf, self._rkbad[c]))
                rotations += 1
                hard = False

            if reason:
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sold.add(c)
                self._cool[c] = day + (STOP_COOL if hard else REORDER_GAP)
                ft = self._feat.get(c)
                if ft:
                    self._attr.append((up, ft[0], ft[1]))
                events.append(("exit", c, up, reason))
                continue

            wgt = ph.get("weight")
            if _ok(wgt) and float(wgt) > MAX_W and len(pos) >= 6:
                frac = 1.0 - TRIM_TO / float(wgt)
                if frac >= 0.10:
                    trimmed.add(c)
                    orders.append({"code": c, "side": "sell", "fraction": round(frac, 3),
                                   "reason": "trim %.0f%% -> %.0f%% cap, concentration is not conviction"
                                             % (float(wgt) * 100.0, TRIM_TO * 100.0)})

        # ---- de-risking brake: bring gross back toward its braked target by
        # cutting the WEAKEST-ranked lines first. Level 3 is the catastrophe
        # step and carries a refractory period so it cannot chatter; even then
        # the book is throttled to GROSS_L3, never switched off.
        live = [(rank.get(c, 10_000), c, float(pos[c].get("value", 0.0) or 0.0))
                for c in pos if c not in sold and c not in trimmed]
        gross_v = sum(v for _r, _c, v in live)
        target_v = eff_gross * eq
        l3_fired = False
        if dd <= self.DD_L3 and day >= self._l3_until:
            target_v = min(target_v, GROSS_L3 * eq)
            self._l3_until = day + L3_REFRACTORY
            self._no_buy_until = max(self._no_buy_until, day + L3_PAUSE)
            l3_fired = True
        if gross_v > target_v + DERISK_BAND * eq and live:
            live.sort(reverse=True)          # worst rank first
            budget_cuts = len(live) if l3_fired else DERISK_MAX
            tag = "level-3 brake" if l3_fired else "de-risk"
            for _rk, c, v in live:
                if gross_v <= target_v + 0.02 * eq or budget_cuts <= 0 or v <= 0:
                    break
                need = gross_v - target_v
                why = ("%s: book %+.1f%% off its high, gross %.0f%% -> %.0f%%"
                       % (tag, dd * 100.0, gross_v / eq * 100.0, target_v / eq * 100.0))
                if need >= 0.75 * v or v <= 2.0 * MIN_TICKET:
                    orders.append({"code": c, "side": "sell", "all": True, "reason": why})
                    sold.add(c)
                    self._cool[c] = day + REORDER_GAP
                    ft = self._feat.get(c)
                    if ft:
                        up = pos[c].get("unrealized_pct", 0.0)
                        self._attr.append((float(up) if _ok(up) else 0.0, ft[0], ft[1]))
                    gross_v -= v
                else:
                    frac = _clamp(need / v, 0.10, 0.90)
                    orders.append({"code": c, "side": "sell", "fraction": round(frac, 3),
                                   "reason": why})
                    trimmed.add(c)
                    gross_v -= v * frac
                budget_cuts -= 1

        for c in list(self._peak):
            if c not in pos:
                self._peak.pop(c, None)
                self._brk.pop(c, None)
                self._rkbad.pop(c, None)
                self._feat.pop(c, None)

        # ---------------------------------------------------------- entries
        held = [c for c in pos if c not in sold]
        n_pend = len([c for c, d0 in self._ordered.items()
                      if c not in pos and 0 <= day - d0 <= ORDER_GUARD])
        slots = N_SLOTS - len(held) - n_pend
        gross_v = sum(float(pos[c].get("value", 0.0) or 0.0) for c in held)
        gross = gross_v / eq if eq > 0 else 0.0
        sec_n = {}
        for c in held:
            s = sectors.get(c, "Other")
            sec_n[s] = sec_n.get(s, 0) + 1

        cap = MAX_ENTRIES
        if dd_scale < 0.90:
            cap = 2
        if dd_scale < 0.72:
            cap = 1
        if gross < eff_gross - REBUILD_GAP:
            cap = max(cap, REBUILD_ENTRIES if dd_scale >= 0.90 else 3)
        can_buy = (cap > 0 and slots > 0 and not l3_fired
                   and day > self._no_buy_until and gross < eff_gross)

        # proceeds from today's full exits arrive at the same open as the buys
        proceeds = sum(float(pos[c].get("value", 0.0) or 0.0) for c in sold) * 0.985
        room = max(0.0, eff_gross - gross) * eq
        avail = min(cash * CASH_BUFFER + proceeds, room)

        pool = max(10, int(round(self.ENTRY_POOL * (1.0 - FEAR_POOL * fear))))
        off_hi = self.MAX_OFF_HIGH * (1.0 - FEAR_OFFHI * fear)
        bought = 0
        if can_buy and avail >= MIN_TICKET:
            for k, (_s, c, i) in enumerate(scored):
                if bought >= cap or slots <= 0 or avail < MIN_TICKET:
                    break
                if k + 1 > pool:
                    break
                if c in pos or c in sold:
                    continue
                if day <= self._cool.get(c, -1):
                    continue
                if 0 <= day - self._ordered.get(c, -999) <= ORDER_GUARD:
                    continue
                r = rows[c]
                px = r.get("AdjClose")
                s50 = r.get("sma50")
                smid = r.get("sma100")
                if not _ok(smid):
                    smid = r.get("sma200")
                if not (_ok(px) and _ok(s50) and _ok(smid)):
                    continue
                if not (float(px) > float(s50) and float(px) > float(smid)):
                    continue
                r6, r12 = r.get("ret_6m"), r.get("ret_12m")
                trend_ok = (_ok(r6) and float(r6) > 0.0) or (_ok(r12) and float(r12) > 0.0)
                if not trend_ok:
                    continue
                d52 = r.get("dist_52w_high")
                if not _ok(d52) or float(d52) < -off_hi:
                    continue
                t_today = r.get("turnover_sar")
                if not _ok(t_today) or float(t_today) < TURN_TODAY_MIN:
                    continue
                sec = sectors.get(c, "Other")
                if sec_n.get(sec, 0) >= SECTOR_CAP:
                    continue
                ap = r.get("atr_pct")
                ap = float(ap) if _ok(ap) and float(ap) > 0 else TARGET_ATR
                w = TARGET_W * _clamp(TARGET_ATR / ap, SIZE_LO, SIZE_HI)
                w = min(w, MAX_W)
                budget = min(w * eq, avail)
                if budget < MIN_TICKET:
                    continue
                orders.append({
                    "code": c, "side": "buy", "sar": round(budget, 2),
                    "reason": ("rank %d/%d, %.1f%% off the 52w high, ATR %.1f%% -> %.1f%% line"
                               % (k + 1, len(scored), abs(float(d52)) * 100.0,
                                  ap * 100.0, w * 100.0))})
                self._ordered[c] = day
                self._feat[c] = (p_mt[i], p_lt[i])
                sec_n[sec] = sec_n.get(sec, 0) + 1
                avail -= budget
                slots -= 1
                bought += 1

        # ---- top-up: volatility-scaled sizes leave the book structurally
        # under its gross target once every slot is taken. Rather than let cash
        # pile up by accident, add to the single best-ranked healthy holding.
        if (bought == 0 and slots <= 0 and cap > 0 and not l3_fired
                and day > self._no_buy_until and avail >= MIN_TICKET
                and gross < eff_gross - TOPUP_GAP):
            for k, (_s, c, _i) in enumerate(scored):
                if k + 1 > pool:
                    break
                if c not in pos or c in sold or c in trimmed:
                    continue
                wgt = pos[c].get("weight")
                wgt = float(wgt) if _ok(wgt) else MAX_W
                if wgt >= TRIM_TO:
                    continue
                r = rows[c]
                px, s50 = r.get("AdjClose"), r.get("sma50")
                if not (_ok(px) and _ok(s50) and float(px) > float(s50)):
                    continue
                d52 = r.get("dist_52w_high")
                if not _ok(d52) or float(d52) < -off_hi:
                    continue
                budget = min(avail, max(0.0, (TRIM_TO - wgt) * eq))
                if budget < MIN_TICKET:
                    continue
                orders.append({"code": c, "side": "buy", "sar": round(budget, 2),
                               "reason": ("top-up rank %d: book %.0f%% invested against a "
                                          "%.0f%% target" % (k + 1, gross * 100.0,
                                                             eff_gross * 100.0))})
                self._ordered[c] = day
                break

        # -------------------------------------------------------- sentiment
        sent = 0.0
        sent += 1.10 * (breadth - 0.50)
        sent -= 0.90 * fear
        sent += 5.0 * _clamp(own_1d, -0.06, 0.06)
        sent += 0.25 * _clamp(dd / 0.20 + 1.0, -1.0, 1.0)
        if self._brake >= 2:
            sent = min(sent, -0.55)
        sent = 0.55 * self._sent + 0.45 * sent
        sent = _clamp(sent, -1.0, 1.0)
        self._sent = sent
        mood = ("braking" if self._brake >= 2 else
                "guarded" if self._brake == 1 or fear > 0.55 else
                "invested" if gross > 0.60 else "rebuilding")

        # ------------------------------------------------------- sparse note
        note = ""
        if l3_fired:
            note = ("Level-3 brake: book %+.1f%% off its high. Gross cut to %.0f%% by "
                    "selling the weakest-ranked lines; 126-session refractory so this "
                    "cannot chatter. The book is throttled, never switched off."
                    % (dd * 100.0, GROSS_L3 * 100.0))
        elif self._brake != prev_brake:
            note = ("Brake level %d -> %d at %+.1f%% drawdown (fear %.2f, breadth %.0f%%). "
                    "Entries %s, trails scaled to %.0f%% of base."
                    % (prev_brake, self._brake, dd * 100.0, fear, breadth * 100.0,
                       {0: "3/session", 1: "1/session", 2: "off"}[self._brake],
                       tscale * 100.0))
        else:
            big = [e for e in events if abs(e[2]) >= 0.25]
            if big:
                c, up, why = big[0][1], big[0][2], big[0][3]
                note = ("Closed %s at %+.1f%% — %s. Wide leash on winners, short one on "
                        "losers; that asymmetry is the whole book." % (c, up * 100.0, why))
            elif fear >= 0.85 and day % 21 == 0:
                note = ("Fear read pinned (index %.0f%% off its 52w high, breadth %.0f%%): "
                        "trails at %.0f%% of base, %d names still qualify. No cash call, "
                        "the exits do the de-risking."
                        % (i_dd * 100.0, breadth * 100.0, tscale * 100.0, len(scored)))

        out = {"orders": orders, "sentiment": round(sent, 3), "mood": mood}
        if note:
            out["note"] = note
        return out

    # -------------------------------------------------------------- adapt
    def _set(self, name, val, changes):
        lo, hi = self.meta["param_space"][name]
        val = _clamp(float(val), float(lo), float(hi))
        old = float(getattr(self, name))
        if abs(val - old) > 1e-9:
            setattr(self, name, val)
            changes[name] = round(val, 4)

    def adapt(self, feedback):
        if not isinstance(feedback, dict):
            return None
        w = feedback.get("window") or {}
        cum = feedback.get("cumulative") or {}
        ch = {}
        self._n_adapt += 1

        def g(d, k, default=None):
            v = d.get(k)
            return float(v) if _ok(v) else default

        ret = g(w, "ret", 0.0)
        bench = g(w, "bench_ret", 0.0)
        sharpe = g(w, "sharpe", 0.0)
        mdd = g(w, "max_dd", 0.0)
        hr = g(w, "hit_rate")
        pf = g(w, "profit_factor")
        turn = g(w, "turnover", 0.0)
        expo = g(w, "avg_exposure", 0.9)
        cdd = g(cum, "dd_from_peak", 0.0)

        # --- 1. realised drawdown behaviour -> trail widths and brake levels
        # Asymmetric on purpose: the tightening step is larger than the
        # loosening step, so the loop gives ground grudgingly and takes it back
        # quickly. The *live* crash response is the fear ramp inside decide(),
        # which reacts the same session; adapt() only moves the resting width,
        # so it must not also chase the tape or the two double-count.
        self._dd_ema = 0.70 * self._dd_ema + 0.30 * abs(mdd)
        deep = self._dd_ema > 1.35 * DD_TARGET
        shallow = self._dd_ema < 0.65 * DD_TARGET
        if deep:
            self._set("TRAIL_K", self.TRAIL_K - 0.45, ch)
            self._set("TRAIL_HI", self.TRAIL_HI - 0.020, ch)
            self._set("FEAR_SCALE", self.FEAR_SCALE - 0.040, ch)
            self._set("DD_L1", self.DD_L1 + 0.008, ch)
            self._set("DD_L2", self.DD_L2 + 0.008, ch)
            self._set("DD_L3", self.DD_L3 + 0.010, ch)
            self._set("MAX_OFF_HIGH", self.MAX_OFF_HIGH - 0.010, ch)
        elif shallow:
            self._set("TRAIL_K", self.TRAIL_K + 0.35, ch)
            self._set("TRAIL_HI", self.TRAIL_HI + 0.015, ch)
            self._set("FEAR_SCALE", self.FEAR_SCALE + 0.030, ch)
            self._set("DD_L1", self.DD_L1 - 0.006, ch)
            self._set("DD_L2", self.DD_L2 - 0.006, ch)
            self._set("DD_L3", self.DD_L3 - 0.008, ch)
        if cdd <= self.DD_L3:
            # still under the catastrophe line at window end: brake earlier next time
            self._set("DD_L2", self.DD_L2 + 0.010, ch)
            self._set("TRAIL_K", self.TRAIL_K - 0.30, ch)

        # --- 2. exit asymmetry from the hit-rate / profit-factor pair
        if hr is not None and pf is not None:
            if hr >= 0.55 and pf < 1.20:
                # winning often but small: the trail is cutting compounders early
                self._set("TRAIL_K", self.TRAIL_K + 0.40, ch)
                self._set("TRAIL_HI", self.TRAIL_HI + 0.020, ch)
            elif hr <= 0.35 and pf < 1.00:
                # bleeding on both counts: make the losses smaller and faster
                self._set("HARD_STOP", self.HARD_STOP + 0.010, ch)
                self._set("TRAIL_LO", self.TRAIL_LO - 0.008, ch)
            elif hr >= 0.50 and pf >= 1.60:
                self._set("HARD_STOP", self.HARD_STOP - 0.005, ch)

        # --- 3. exposure tracks realised Sharpe and participation
        self._sh_ema = 0.70 * self._sh_ema + 0.30 * sharpe
        want_gross = _clamp(0.880 + 0.055 * self._sh_ema, 0.80, 0.99)
        step = 0.020 if want_gross > self.TARGET_GROSS else -0.020
        if abs(want_gross - self.TARGET_GROSS) > 0.004:
            self._set("TARGET_GROSS", self.TARGET_GROSS + step, ch)
        if bench > 0.03 and ret < 0.5 * bench and expo < 0.80 and not deep:
            self._set("TARGET_GROSS", self.TARGET_GROSS + 0.015, ch)
            self._set("ENTRY_POOL", self.ENTRY_POOL + 2.0, ch)
            self._set("MAX_OFF_HIGH", self.MAX_OFF_HIGH + 0.010, ch)
        elif bench < -0.02 and ret < bench:
            self._set("ENTRY_POOL", self.ENTRY_POOL - 2.0, ch)

        # --- 4. rank buffer from realised turnover
        if turn > 1.10:
            self._set("RANK_BUFFER", self.RANK_BUFFER + 3.0, ch)
        elif turn < 0.35 and ret < bench:
            self._set("RANK_BUFFER", self.RANK_BUFFER - 2.0, ch)

        # --- 5. momentum horizon weights from per-trade attribution
        attr_n = len(self._attr)
        if attr_n >= ATTR_MIN_N:
            m_mt = sum(a[1] for a in self._attr) / attr_n
            m_lt = sum(a[2] for a in self._attr) / attr_n
            s_mt = s_lt = 0.0
            for p, a_mt, a_lt in self._attr:
                sg = 1.0 if p > 0 else -1.0
                s_mt += sg * (a_mt - m_mt)
                s_lt += sg * (a_lt - m_lt)
            s_mt /= attr_n
            s_lt /= attr_n
            d = s_mt - s_lt
            if abs(d) > 0.020:
                st = 0.12 if d > 0 else -0.12
                self._set("W_MT", self.W_MT + st, ch)
                self._set("W_LT", self.W_LT - 0.6 * st, ch)
        self._attr = self._attr[-200:] if attr_n < ATTR_MIN_N else []

        # --- ordering invariants (brake ladder must stay monotone)
        if self.DD_L2 > self.DD_L1 - 0.03:
            self._set("DD_L2", self.DD_L1 - 0.03, ch)
        if self.DD_L3 > self.DD_L2 - 0.04:
            self._set("DD_L3", self.DD_L2 - 0.04, ch)
        if self.TRAIL_HI < self.TRAIL_LO + 0.04:
            self._set("TRAIL_HI", self.TRAIL_LO + 0.04, ch)

        note = ("w%d ret %+.1f%% vs bench %+.1f%%, dd %.1f%% (ema %.1f%%), sharpe %.2f, "
                "hit %s, pf %s -> trail %.1fxATR [%.0f%%-%.0f%%], fear x%.2f, "
                "brakes %.0f/%.0f/%.0f%%, gross %.0f%%"
                % (self._n_adapt, ret * 100.0, bench * 100.0, abs(mdd) * 100.0,
                   self._dd_ema * 100.0, sharpe,
                   ("%.0f%%" % (hr * 100.0)) if hr is not None else "n/a",
                   ("%.2f" % pf) if pf is not None else "n/a",
                   self.TRAIL_K, self.TRAIL_LO * 100.0, self.TRAIL_HI * 100.0,
                   self.FEAR_SCALE, self.DD_L1 * 100.0, self.DD_L2 * 100.0,
                   self.DD_L3 * 100.0, self.TARGET_GROSS * 100.0))
        return {"changes": ch, "note": note}


STRATEGY = Defense()
