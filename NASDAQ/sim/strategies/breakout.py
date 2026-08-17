"""breakout — fresh-52-week-high desk for the AAOIFI-screened NASDAQ tape.

SCHOOL: breakouts and fresh highs. The skeleton is the one that survived the TASI
out-of-sample walk-back — selectivity, a liquidity floor, small fast losses, very
wide trails on winners — but four of its organs are deliberately different,
because a deep US tape is not Tadawul:

  1. NO LIQUIDITY CEILING. On Tadawul the mega-caps were index proxies and had to
     be screened out. Here the opposite holds: the deepest names print the
     cleanest multi-year trends. The screen keeps only a FLOOR on dollar
     turnover, whose job is to kill the untradeable tail; adapt() then steers
     that floor from the realized turnover of winners versus losers.
  2. THE 200-DAY OUTRANKS THE 50-DAY. Gating on the index's 50-day — the TASI
     rule — is actively harmful here: it whipsaws. Exposure instead rides a
     four-rung ladder scoring the index two points for its 200-day and one for
     its 50-day, so a regime error costs size, never the whole book. A binary
     on/off switch is what sank the TASI in-sample champion out-of-sample.
  3. A DEAD-MONEY CLOCK IS NOT AN EXIT. A pure "flat for N sessions, sell"
     time stop is the single most expensive rule this school can carry on
     NASDAQ, because the compounders that make the year spend months
     consolidating. A position is only recycled when the clock has run out AND
     the name has lost leadership (relative strength negative, or price back
     under its own 50-day).
  4. NOTHING TAKES PROFIT BUT THE TRAIL. No scale-outs, no targets, no
     pyramiding into extension. Single-name risk is bounded by trimming an
     oversized line back toward a normal weight, which is rebalancing rather
     than selling a winner.

THE RULEBOOK
------------
UNIVERSE (re-derived every session; never a fixed list)
  price >= PX_MIN, a slow (~50-session) EMA of dollar turnover >= LIQ_FLOOR, today's
  turnover >= a fraction of that floor, ATR% inside [ATR_LO, ATR_HI].

TRIGGER (all must hold)
  close within |D52_MAX| of the 52-week high — the base has actually resolved;
  close above BOTH sma50 and sma200 — the trend exists on both horizons;
  ret_3m >= 0 and rs_bench_3m >= RS_MIN — it must be leading the index. In a
  panel study of every (name, session) pair in the in-sample years, index-
  relative strength was by far the strongest discriminator of forward returns
  among fresh-high names; raw momentum magnitude was the weakest.

RANK  proximity to the high + relative strength + an adaptive blend of 3m/6m/12m
  thrust (each capped, so one extreme number cannot buy a ranking), minus a
  parabolic-extension penalty: names already vertical over one month have a
  negative median forward edge. There is deliberately no volume term — on this
  tape a volume-confirmation score measurably subtracted value, and a rule that
  does not pay is a rule that only adds fragility out of sample.

SIZE  weight = RISK_PER_TRADE / (STOP_ATR x ATR%), clamped to [W_MIN, W_MAX], so
  the volatility term only bites at the volatile end — which is exactly why the
  ATR ceiling can stay generous. Gross book is capped by the regime ladder times
  an adaptive exposure scalar; a book far under its own cap is allowed to rebuild
  at double pace, because being slow to re-enter a repaired tape is the other
  half of the cost of a regime rule.

EXITS (asymmetric, mechanical, in priority order)
  initial stop   cost - STOP_ATR x ATR(at entry), live until the trail arms;
  hard stop      HARD_STOP — small, fast, unarguable;
  trail          peak-since-entry - TRAIL_ATR x ATR, armed only once the trade is
                 up TRAIL_ARM, with the ATR reference clamped to [0.6x, 1.25x] of
                 its entry value so a volatility spike cannot balloon the stop,
                 and the giveback held inside [GIVEBACK_LO, GIVEBACK_HI];
  trend break    while the index sits below both its own MAs, a close back under
                 the name's 50-day ends the position;
  dead money     TIME_STOP sessions under TIME_MIN *and* leadership lost.

CIRCUIT BREAKERS  drawdown past DD_TRIM halves the cap while the tape is also
  broken (it releases the moment the index reclaims both MAs — a desk that stays
  small through the repair misses the recovery); past DD_FLAT the book stands
  down for FLAT_DAYS. Both measure drawdown from a rolling one-year peak that is
  re-anchored when a breaker fires, so a breaker can never latch on permanently.
  No new entries for CRASH_COOL sessions after any index day worse than
  CRASH_DAY.

BACK-PROPAGATION  adapt() runs every 63 sessions on realized window feedback:
  exposure follows realized Sharpe and benchmark shortfall, stop width follows
  hit rate, trail width follows the realized payoff ratio, selectivity follows
  under/over-trading, the liquidity floor follows the turnover of winners versus
  losers, and the 3m/6m/12m rank weights follow whichever horizon's trades
  actually paid. Every parameter is clamped to meta["param_space"], every step is
  small, and every parameter is pulled a few percent back toward its default each
  window, so a long out-of-sample run cannot ratchet itself into a corner.

No dates, no per-ticker plans, no memorised tape. Deterministic, stdlib only, no
IO, every read NaN-guarded.
"""

from __future__ import annotations

from strategy_base import Strategy

INF = float("inf")

# --- universe screen -------------------------------------------------------
PX_MIN = 3.0
LIQ_FLOOR0 = 25_000_000.0     # 30d EMA of dollar turnover — floor only, no ceiling
TURN_TODAY_FRAC = 0.30        # today's turnover vs the floor (halted/dead-tape guard)
TURN_ALPHA = 0.04             # ~50-session EMA: trailing liquidity should be slow
ATR_LO = 0.008
ATR_HI0 = 0.070

# --- breakout trigger ------------------------------------------------------
D52_MAX0 = -0.030             # close must be within 3% of the 52-week high
RS_MIN0 = 0.02                # must lead the index over 3 months
RET3M_MIN = 0.0

# --- portfolio -------------------------------------------------------------
MAX_POS = 9
RISK0 = 0.012
STOP_ATR0 = 2.5
W_MIN, W_MAX = 0.06, 0.15
CONC_CAP, CONC_BACK = 0.22, 0.16   # trim an oversized winner back, never scale out
MIN_BUY = 4_000.0
ENTRIES_PER_DAY = 3
COOL_LOSS, COOL_WIN = 8, 3
ORDER_GUARD = 3
PACE_BOOST = True                  # rebuild faster when the book is far under its cap

# --- exits -----------------------------------------------------------------
HARD_STOP = -0.12
TRAIL_ATR0 = 6.0
TRAIL_ARM0 = 0.12
GIVEBACK_LO, GIVEBACK_HI = 0.08, 0.28
TIME_STOP0 = 30
TIME_MIN = 0.03
STALE_NEEDS_WEAK = True   # recycle a flat position only if it has ALSO lost leadership

# --- regime / risk switches ------------------------------------------------
REG_CAP = (0.00, 0.30, 0.95, 1.00)   # index vs sma200 (2 pts) and sma50 (1 pt)
BREADTH_WEAK = 0.35
BREADTH_MULT = 0.60
DD_LOOKBACK = 252
DD_TRIM, DD_FLAT = 0.15, 0.24
FLAT_DAYS = 10
CRASH_DAY = -0.030
CRASH_COOL = 3
# A broken tape does NOT tighten the trail — squeezing a stop into a high-volatility
# downtape just guarantees selling the lows. It gets its own clean exit instead: a
# close back under the name's own 50-day while the index is below both of its MAs.
BEAR_BREAK_MIN_HELD = 3
EXPO0 = 0.95

# --- rank weights (momentum horizon blend is adaptive) ---------------------
W3_0, W6_0, W12_0 = 0.40, 0.35, 0.25
W_PROX = 7.0
W_RS = 1.8
RC3, RC6, RC12 = 0.50, 0.80, 1.00  # caps on how much raw thrust can score
W_EXT = 0.9                    # parabolic-extension penalty
EXT_FREE = 0.25                # one-month return that counts as "not vertical"


def _ok(x):
    return isinstance(x, (int, float)) and x == x and -INF < x < INF


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class Breakout(Strategy):
    meta = {
        "handle": "breakout",
        "name": "Breakout",
        "style": ("buys liquid NASDAQ names printing fresh 52-week highs while leading "
                  "the index, sizes by ATR, cuts losers fast and trails winners very wide"),
        "risk_style": "selective trend-continuation breakout momentum",
        "color": "#888888",
        "param_space": {
            "RISK_PER_TRADE": [0.006, 0.020],
            "STOP_ATR": [1.8, 3.6],
            "TRAIL_ATR": [3.5, 8.0],
            "TRAIL_ARM": [0.04, 0.20],
            "RS_MIN": [-0.05, 0.20],
            "D52_MAX": [-0.060, -0.005],
            "ATR_HI": [0.030, 0.100],
            "LIQ_FLOOR": [5_000_000.0, 300_000_000.0],
            "EXPO": [0.55, 1.00],
            "TIME_STOP": [15, 45],
            "W3": [0.10, 0.70],
            "W6": [0.10, 0.70],
            "W12": [0.10, 0.70],
        },
    }

    _DEFAULTS = {
        "RISK_PER_TRADE": RISK0, "STOP_ATR": STOP_ATR0, "TRAIL_ATR": TRAIL_ATR0,
        "TRAIL_ARM": TRAIL_ARM0, "RS_MIN": RS_MIN0, "D52_MAX": D52_MAX0,
        "ATR_HI": ATR_HI0, "LIQ_FLOOR": LIQ_FLOOR0, "EXPO": EXPO0,
        "TIME_STOP": float(TIME_STOP0), "W3": W3_0, "W6": W6_0, "W12": W12_0,
    }
    _MEAN_REVERT = 0.06        # pull every parameter back toward its default each window

    def __init__(self):
        self.p = dict(self._DEFAULTS)
        self._turn = {}          # code -> EMA of dollar turnover
        self._peak = {}          # code -> highest close since entry
        self._atr0 = {}          # code -> ATR at entry
        self._entry_day = {}     # code -> sim day of the fill
        self._feat = {}          # code -> entry features, for adapt() attribution
        self._cool = {}          # code -> day until which re-entry is barred
        self._ordered = {}       # code -> day an order was queued (dupe guard)
        self._closed = []        # window's closed trades with entry features
        self._flat = False
        self._flat_until = -1
        self._flat_dd = 0.0
        self._dd_anchor = 0
        self._no_buy_until = -1
        self._reg_prev = None
        self._sent_prev = 0.0
        self._n_adapt = 0

    # ------------------------------------------------------------- helpers
    def _regime(self, view, breadth):
        ix = view.get("IXIC") or {}
        c = ix.get("AdjClose")
        if not _ok(c):
            c = ix.get("Close")
        s50, s200 = ix.get("sma50"), ix.get("sma200")
        if not (_ok(c) and (_ok(s50) or _ok(s200))):
            # benchmark row missing or still warming up: fall back to breadth so a
            # data gap degrades the size of the book rather than switching it off
            return (3 if breadth >= 0.55 else 2 if breadth >= 0.40 else 1), \
                REG_CAP[3 if breadth >= 0.55 else 2 if breadth >= 0.40 else 1]
        # The 200-day defines the primary trend and carries most of the weight; the
        # 50-day is only a secondary confirmation. Treating them symmetrically makes
        # the ladder ride the 50-day's noise, which is the expensive mistake here.
        rungs = 0
        if _ok(s200) and c > s200:
            rungs += 2
        elif not _ok(s200) and _ok(s50) and c > s50:
            rungs += 2      # pre-200d warm-up: the 50-day stands in for the primary trend
        if _ok(s50) and c > s50:
            rungs += 1
        cap = REG_CAP[rungs]
        if breadth < BREADTH_WEAK:
            cap *= BREADTH_MULT
        return rungs, cap

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        p = self.p
        day = int(ctx.get("day_index", 0) or 0)
        pos = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        eq = float(portfolio.get("equity", 0.0) or 0.0)
        if not _ok(eq) or eq <= 0:
            eq = 1.0
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = breadth if _ok(breadth) else 0.5
        bret = ctx.get("tasi_ret_1d", 0.0)
        bret = bret if _ok(bret) else 0.0

        # Drawdown is measured from a ROLLING one-year peak that is additionally
        # re-anchored whenever the circuit breaker fires. An all-time (or even a
        # rolling) peak that is never re-anchored latches the breaker on for months
        # after one bad quarter — by far the most expensive failure this family of
        # rules has, because it turns a risk control into a permanent short of the
        # market's best recoveries.
        hist = ctx.get("equity_history") or [eq]
        lo = max(self._dd_anchor, len(hist) - DD_LOOKBACK, 0)
        window = hist[lo:] or [eq]
        peak = max(window)
        dd = (eq / peak - 1.0) if peak > 0 else 0.0

        # --- causal liquidity state -------------------------------------
        turn = self._turn
        alpha = TURN_ALPHA
        for c, r in view.items():
            t = r.get("turnover_sar")
            if _ok(t) and t >= 0.0:
                prev = turn.get(c)
                turn[c] = t if prev is None else prev + alpha * (t - prev)

        rungs, cap = self._regime(view, breadth)
        bear = rungs == 0
        if not self._flat and dd <= -DD_FLAT:
            self._flat, self._flat_until, self._flat_dd = True, day + FLAT_DAYS, dd
            self._dd_anchor = len(hist) - 1      # re-anchor: the bleed is being stopped
            dd = 0.0
        elif self._flat and day > self._flat_until and rungs >= 2:
            self._flat = False
            self._dd_anchor = len(hist) - 1
        flat = self._flat
        # Halve risk while BOTH the book and the tape are hurt. Once the index is
        # back above both its moving averages the trim releases — a trend desk that
        # stays small through the repair is a trend desk that misses the recovery.
        if dd <= -DD_TRIM and rungs < 3:
            cap *= 0.5
        if flat:
            cap = 0.0
        cap *= p["EXPO"]
        if bret <= CRASH_DAY:
            self._no_buy_until = max(self._no_buy_until, day + CRASH_COOL)

        orders, notes, sold = [], [], set()

        # ------------------------------------------------------- exits first
        # A falling exposure cap never flushes the book — it only stops new risk.
        # Positions leave on their own stops, plus one extra trend-break rule while
        # the tape is broken. Graded, not binary.
        stop_atr = p["STOP_ATR"]
        trail_atr = p["TRAIL_ATR"]
        arm = p["TRAIL_ARM"]
        tstop = int(p["TIME_STOP"])
        for c, ph in pos.items():
            r = view.get(c)
            px = r.get("Close") if r is not None else None
            up = ph.get("unrealized_pct", 0.0)
            up = up if _ok(up) else 0.0
            if _ok(px) and px > 0:
                self._peak[c] = max(self._peak.get(c, px), px)
            pk = self._peak.get(c)
            a0 = self._atr0.get(c)
            atr = r.get("atr14") if r is not None else None
            held = day - self._entry_day.get(c, day)
            cost = ph.get("avg_cost")
            reason = None

            if _ok(px) and _ok(cost) and cost > 0 and _ok(a0) and a0 > 0 and up < arm:
                if px <= cost - stop_atr * a0:
                    reason = "initial stop: %.2f through %.2f" % (px, cost - stop_atr * a0)
            if reason is None and up <= HARD_STOP:
                reason = "hard stop %+.1f%%" % (100.0 * up)
            if reason is None and _ok(px) and _ok(pk) and pk > 0 and up >= arm:
                ref = atr if (_ok(atr) and atr > 0) else a0
                if _ok(a0) and a0 > 0 and _ok(ref):
                    ref = _clamp(ref, 0.6 * a0, 1.25 * a0)
                if _ok(ref) and ref > 0:
                    give = _clamp(trail_atr * ref / pk, GIVEBACK_LO, GIVEBACK_HI)
                    if px <= pk * (1.0 - give):
                        reason = ("trail: %.2f under peak %.2f less %.0f%%, banked %+.1f%%"
                                  % (px, pk, 100.0 * give, 100.0 * up))
            if reason is None and bear and held >= BEAR_BREAK_MIN_HELD and _ok(px) and r is not None:
                s50 = r.get("sma50")
                if _ok(s50) and px < s50:
                    reason = "bear-tape trend break: close under its 50d, %+.1f%%" % (100.0 * up)
            # Dead-money recycle. NOT a pure clock: a breakout that consolidates for
            # two months and then runs is the whole business, so the position only
            # gets recycled if it has ALSO lost its leadership (index-relative
            # strength gone negative, or price back under its own 50-day).
            if reason is None and held >= tstop and up < TIME_MIN and r is not None:
                rs = r.get("rs_bench_3m")
                s50 = r.get("sma50")
                if (not STALE_NEEDS_WEAK) or (_ok(rs) and rs < 0.0) or (
                        _ok(s50) and _ok(px) and px < s50):
                    reason = ("stale: %d sessions for %+.1f%% and leadership gone"
                              % (held, 100.0 * up))
            if reason is None and flat:
                reason = ("circuit breaker: book %+.1f%% off its high"
                          % (100.0 * self._flat_dd))

            if reason:
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sold.add(c)
                self._cool[c] = day + (COOL_WIN if up > 0 else COOL_LOSS)
                self._record_close(c, up, held, reason)
                if up <= -0.10 or up >= 0.35:
                    notes.append("exit %s %+.1f%% — %s" % (c, 100.0 * up, reason))
                continue

            # concentration control: trim an oversized line, never scale a winner out
            w = ph.get("weight", 0.0)
            if _ok(w) and w > CONC_CAP:
                orders.append({"code": c, "side": "sell",
                               "fraction": round(1.0 - CONC_BACK / w, 4),
                               "reason": "trim %.0f%% line back to %.0f%%"
                                         % (100.0 * w, 100.0 * CONC_BACK)})

        for c in list(self._peak):
            if c not in pos:
                self._peak.pop(c, None)
                self._atr0.pop(c, None)
                self._entry_day.pop(c, None)
                self._feat.pop(c, None)

        # ------------------------------------------------------------ entries
        live = [(c, ph) for c, ph in pos.items() if c not in sold]
        gross = sum(ph.get("value", 0.0) or 0.0 for _, ph in live) / eq
        n_pend = sum(1 for c, d0 in self._ordered.items()
                     if c not in pos and 0 <= day - d0 <= ORDER_GUARD)
        slots = MAX_POS - len(live) - n_pend
        room = (cap - gross) * eq
        open_ok = (cap > 0.0 and day > self._no_buy_until
                   and cash >= MIN_BUY and room >= MIN_BUY)
        can_buy = open_ok and slots > 0

        risk = p["RISK_PER_TRADE"] * (0.6 if (dd <= -DD_TRIM and rungs < 3) else 1.0)

        cands = []
        if can_buy:
            floor = p["LIQ_FLOOR"]
            t_today_min = floor * TURN_TODAY_FRAC
            d52_max, rs_min, atr_hi = p["D52_MAX"], p["RS_MIN"], p["ATR_HI"]
            w3, w6, w12 = p["W3"], p["W6"], p["W12"]
            for c, r in view.items():
                if c == "IXIC" or c in pos or c in sold:
                    continue
                if day <= self._cool.get(c, -1):
                    continue
                if 0 <= day - self._ordered.get(c, -999) <= ORDER_GUARD:
                    continue
                d52 = r.get("dist_52w_high")
                if not _ok(d52) or d52 < d52_max:
                    continue
                px = r.get("Close")
                if not _ok(px) or px < PX_MIN:
                    continue
                tt = turn.get(c)
                if tt is None or tt < floor:
                    continue
                t_today = r.get("turnover_sar")
                if not _ok(t_today) or t_today < t_today_min:
                    continue
                apct = r.get("atr_pct")
                if not _ok(apct) or apct < ATR_LO or apct > atr_hi:
                    continue
                s50, s200 = r.get("sma50"), r.get("sma200")
                if not (_ok(s50) and px > s50 and _ok(s200) and px > s200):
                    continue
                rs = r.get("rs_bench_3m")
                if not _ok(rs) or rs < rs_min:
                    continue
                r3 = r.get("ret_3m")
                if not _ok(r3) or r3 < RET3M_MIN:
                    continue
                r6 = r.get("ret_6m")
                r6 = r6 if _ok(r6) else 0.0
                r12 = r.get("ret_12m")
                r12 = r12 if _ok(r12) else r6
                r1m = r.get("ret_1m")
                r1m = r1m if _ok(r1m) else 0.0
                sc = W_PROX * _clamp(d52 + 0.06, 0.0, 0.12)
                sc += w3 * _clamp(r3, 0.0, RC3)
                sc += w6 * _clamp(r6, 0.0, RC6)
                sc += w12 * _clamp(r12, 0.0, RC12)
                sc += W_RS * _clamp(rs, -0.2, 0.8)
                sc -= W_EXT * max(0.0, r1m - EXT_FREE)
                cands.append((sc, c, apct, d52, rs, r3, r6, r12, tt, r.get("atr14"), px))
            cands.sort(key=lambda t: (-t[0], t[1]))

        avail = min(cash, room)
        # Normal pace is a few names a session, but a book sitting far below its own
        # regime cap (just after a shake-out, or at the very start) is allowed to
        # rebuild faster: being slow to re-enter a repaired tape is the other half of
        # the cost of a regime rule.
        pace = ENTRIES_PER_DAY + (ENTRIES_PER_DAY if (PACE_BOOST and gross < 0.5 * cap) else 0)
        bought = 0
        for cd in cands:
            if bought >= pace or slots <= 0 or avail < MIN_BUY:
                break
            sc, c, apct, d52, rs, r3, r6, r12, tt, atr14, px = cd
            stop_d = max(0.03, stop_atr * apct)
            w = _clamp(risk / stop_d, W_MIN, W_MAX)
            usd = min(w * eq, avail)
            if usd < MIN_BUY:
                break
            orders.append({"code": c, "side": "buy", "sar": round(usd, 2),
                           "reason": "%.1f%% off 52w high, rs %+.2f, ATR %.1f%% -> %.0f%% line"
                                     % (100.0 * abs(d52), rs, 100.0 * apct, 100.0 * w)})
            self._ordered[c] = day
            self._entry_day[c] = day + 1
            self._atr0[c] = atr14 if (_ok(atr14) and atr14 > 0) else (apct * px)
            self._peak[c] = px
            self._feat[c] = {"r3": r3, "r6": r6, "r12": r12, "rs": rs,
                             "turn": tt, "atr": apct, "day": day + 1}
            avail -= usd
            bought += 1
            slots -= 1

        # ------------------------------------------------------- journal/tone
        note = ""
        if self._reg_prev is not None and rungs != self._reg_prev:
            note = ("regime %d->%d rung (index vs its 200d/50d), breadth %.0f%%, "
                    "exposure cap %.0f%%" % (self._reg_prev, rungs, 100.0 * breadth, 100.0 * cap))
        elif notes:
            note = notes[0]
        self._reg_prev = rungs

        sent = 0.8 * (breadth - 0.5) + 0.20 * (rungs - 1.5) + 4.0 * bret
        if cap <= 0.0:
            sent = min(sent, -0.5)
        sent = _clamp(0.5 * self._sent_prev + 0.5 * sent, -1.0, 1.0)
        self._sent_prev = sent
        mood = ("standing down" if cap <= 0.0 else
                "hunting" if not live else "riding trends")
        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}

    def _record_close(self, code, up, held, reason):
        f = self._feat.get(code)
        if f is None:
            return
        self._closed.append({"ret": up if _ok(up) else 0.0, "held": held,
                             "reason": reason[:12], "r3": f["r3"], "r6": f["r6"],
                             "r12": f["r12"], "rs": f["rs"], "turn": f["turn"]})
        if len(self._closed) > 200:
            del self._closed[:-200]

    # --------------------------------------------------------------- adapt
    def adapt(self, feedback):
        """Deterministic, bounded, small-step back-propagation on realized results."""
        p = self.p
        before = dict(p)
        space = self.meta["param_space"]
        fb = feedback or {}
        w = fb.get("window") or {}

        def num(key, default=0.0):
            v = w.get(key)
            return float(v) if _ok(v) else default

        ret = num("ret")
        bench = num("bench_ret")
        sharpe = num("sharpe")
        max_dd = num("max_dd")
        expo = _clamp(num("avg_exposure", 0.0), 0.0, 1.5)
        turnover = num("turnover")
        hr = w.get("hit_rate")
        hr = float(hr) if _ok(hr) else None
        pf = w.get("profit_factor")
        pf = float(pf) if _ok(pf) else None
        n_sells = int(num("n_sells", 0))

        # 0) pull every parameter a little toward its default (anti-ratchet)
        k = self._MEAN_REVERT
        for name, d0 in self._DEFAULTS.items():
            p[name] = p[name] + k * (d0 - p[name])

        # 1) EXPOSURE follows what realized Sharpe supports, and benchmark shortfall
        if sharpe > 1.0:
            p["EXPO"] += 0.04
        elif sharpe < 0.0:
            p["EXPO"] -= 0.06
        elif sharpe < 0.35:
            p["EXPO"] -= 0.015
        if ret > bench and sharpe > 0.5:
            p["EXPO"] += 0.02
        if bench > 0.02 and ret < bench - 0.04 and expo < 0.60:
            p["EXPO"] += 0.05          # too defensive into a rising tape
        if max_dd < -0.18:
            p["EXPO"] -= 0.04

        # 2) RISK per trade follows realized drawdown
        if max_dd < -0.15:
            p["RISK_PER_TRADE"] -= 0.0010
        elif max_dd > -0.07 and sharpe > 0.5:
            p["RISK_PER_TRADE"] += 0.0008

        # 3) STOP width follows hit rate: shaken out -> wider, bleeding -> tighter
        if hr is not None and n_sells >= 4:
            if hr < 0.38:
                p["STOP_ATR"] += 0.15
            elif hr > 0.60 and (pf is None or pf < 1.2):
                p["STOP_ATR"] -= 0.15

        # 4) TRAIL width follows the realized payoff ratio (avg win / avg loss)
        if pf is not None and hr is not None and 0.0 < hr < 1.0 and n_sells >= 4:
            payoff = pf * (1.0 - hr) / hr
            if payoff < 1.6:
                p["TRAIL_ATR"] += 0.30      # winners are being clipped too early
                p["TRAIL_ARM"] += 0.010
            elif payoff > 3.5 and hr < 0.35:
                p["TRAIL_ATR"] -= 0.20
                p["TRAIL_ARM"] -= 0.005

        # 5) SELECTIVITY: pickier when losing into a rising tape, looser when starved
        if bench > 0.0 and ret < min(0.0, bench - 0.03):
            p["RS_MIN"] += 0.010
            p["D52_MAX"] += 0.003
            p["ATR_HI"] -= 0.003
        elif expo < 0.62 and bench > 0.0:
            p["RS_MIN"] -= 0.010
            p["D52_MAX"] -= 0.004
            p["ATR_HI"] += 0.003

        # 6) TIME STOP follows churn
        if turnover > 4.0:
            p["TIME_STOP"] += 2.0
        elif turnover < 1.0 and expo < 0.70:
            p["TIME_STOP"] -= 2.0

        # 7) LIQUIDITY FLOOR from the turnover of this window's winners vs losers
        wins = [t for t in self._closed if t["ret"] > 0 and _ok(t["turn"])]
        loss = [t for t in self._closed if t["ret"] <= 0 and _ok(t["turn"])]
        if len(wins) >= 3 and len(loss) >= 3:
            mw = sorted(t["turn"] for t in wins)[len(wins) // 2]
            ml = sorted(t["turn"] for t in loss)[len(loss) // 2]
            if ml > 0 and mw > ml * 1.30:
                p["LIQ_FLOOR"] *= 1.15
            elif mw > 0 and ml > mw * 1.30:
                p["LIQ_FLOOR"] *= 0.87

        # 8) MOMENTUM HORIZON weights toward whichever lookback's trades paid
        if len(self._closed) >= 5:
            rets = [t["ret"] for t in self._closed]
            mr = sum(rets) / len(rets)
            for key, pname in (("r3", "W3"), ("r6", "W6"), ("r12", "W12")):
                xs = [t[key] for t in self._closed if _ok(t[key])]
                if len(xs) < 5:
                    continue
                mx = sum(xs) / len(xs)
                cov = sum((t[key] - mx) * (t["ret"] - mr)
                          for t in self._closed if _ok(t[key]))
                p[pname] += 0.03 if cov > 0 else -0.03
        self._closed = []

        # --- clamp everything into its declared space, then renormalise weights
        for name, (lo, hi) in space.items():
            p[name] = _clamp(p[name], lo, hi)
        s = p["W3"] + p["W6"] + p["W12"]
        if s > 0:
            scale = (W3_0 + W6_0 + W12_0) / s
            for pname in ("W3", "W6", "W12"):
                p[pname] = _clamp(p[pname] * scale, *space[pname])
        p["TIME_STOP"] = float(int(round(p["TIME_STOP"])))

        changes = {}
        for name in space:
            a, b = before[name], p[name]
            if abs(b - a) > (1e-6 * max(1.0, abs(a))):
                changes[name] = round(b, 6) if abs(b) < 1e6 else round(b, 1)
        self._n_adapt += 1
        note = ("w%d ret %+.1f%% vs bench %+.1f%%, sharpe %.2f, dd %.1f%%, hit %s, pf %s, "
                "expo %.0f%% -> cap %.2f, stop %.2f, trail %.2f, rs>=%.3f, floor %.0fM"
                % (self._n_adapt, 100.0 * ret, 100.0 * bench, sharpe, 100.0 * max_dd,
                   ("%.2f" % hr) if hr is not None else "na",
                   ("%.2f" % pf) if pf is not None else "na",
                   100.0 * expo, p["EXPO"], p["STOP_ATR"], p["TRAIL_ATR"],
                   p["RS_MIN"], p["LIQ_FLOOR"] / 1e6))
        return {"changes": changes, "note": note}


STRATEGY = Breakout()
