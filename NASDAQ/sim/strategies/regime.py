"""regime — regime & rotation desk on the AAOIFI-screened NASDAQ universe.

Thesis
------
Two decisions decide a NASDAQ book: HOW MUCH to own, and WHICH names. This desk
separates them completely and lets each be answered by the evidence that
actually bears on it.

  * HOW MUCH is a market-wide question. A four-signal regime score (index trend,
    market breadth, index momentum, market stress) collapses into one number in
    [-1, +1] which maps onto a small set of decisive, QUANTISED exposure rungs.
    Rungs, not a continuous dial: a book that drifts 3% at a time never actually
    de-risks, and a book that flips between 0% and 100% churns itself to death.
    Hysteresis bands stop the rung chattering.
  * WHICH NAMES is a cross-sectional question, answered only inside whatever
    exposure the regime allows: risk-adjusted multi-horizon momentum
    percentiles, tilted by sector rotation, sized inverse-volatility.

The exposure floor is deliberately NOT zero. On this exchange the base rate is a
secular advance punctuated by violent corrections, so a regime model that goes
all the way to cash pays for its insurance in missed compounding — every
measurement in this arena's predecessor said index timing is a fee. The floor
buys survival; the rungs, the overrides and the entry screen buy the rest.

THE RULEBOOK
------------
1. REGIME SCORE, rebuilt every session from general market state only:
   trend    (w 0.34) index vs its 20/50/100/200-day averages, each gap
                     normalised by that horizon's own typical dispersion
   breadth  (w 0.28) share of the universe above its 50-day line, plus the
                     5-vs-20 session slope of that share
   momentum (w 0.12) index 1m and 3m returns, scaled
   stress   (w 0.26, SUBTRACTIVE) realised vol against its own long-run norm,
                     index distance from its 52-week high, consecutive down days

2. EXPOSURE RUNGS. score -> ramp[ramp_lo, ramp_hi] -> gross in
   [gross_floor, 1.0], quantised to 25% rungs, moved only when the continuous
   read leaves a 9% hysteresis band. The book carries fewer names as the rung
   comes down, so de-risking sells the weakest names outright instead of
   shaving every line and paying commission on all of them.

3. SAME-SESSION OVERRIDES — no confirmation, they fire the day they trigger:
   * CIRCUIT BREAKER — an index air-pocket (<= panic_ret) while breadth is thin
     caps gross at 35% for three sessions and bars every new entry.
   * THRUST — breadth vaulting from below thrust_lo to above thrust_hi inside
     thrust_win sessions forces gross to 100% and cancels the equity stop.
     Bottoms do not ring a bell; participation is the closest thing to one, and
     it leads every trend signal by weeks. The thrust is cancelled early if the
     index cannot hold its own 20-day line.
   * EQUITY STOP — own drawdown past eq_stop_dd caps the book until the regime
     score prints clean again. My own equity curve is a regime signal too.

4. OPPORTUNITY GATE — the second, independent risk control. Exposure is
   min(regime rung, what actually qualifies). When nothing passes the entry
   screen the book holds cash whatever the score says; this is what carried the
   desk through the in-sample bear year, not the dial.

5. NAMES. Liquidity: 20-day dollar turnover >= max($10M, 10% of the universe
   median) — an absolute floor AND a relative one, because dollar volumes are
   not stationary across a decade. Trend: above sma50 and sma100, 3-month
   return positive, ATR% <= 10%, price >= $5. Score: percentile blend of
   vol-adjusted 1m/3m/6m/12m returns + proximity to the 52-week high +
   relative strength vs the composite + a sector-rotation tilt (sectors ranked
   on their own members' scores), which swings toward low-volatility names as
   exposure comes down. Percentiles, never absolute thresholds: the bar is the
   field, so the screen cannot go stale as the market re-prices.

6. BOOK. Up to 14 slots, inverse-volatility weights, 13% cap per name, 6 per
   sector, full re-rank every 13 sessions with a 24-rank hysteresis buffer so
   nothing is sold for slipping one place. Off-cycle sessions may only deploy
   into the plan or cut exposure — a top-up is never allowed to become a
   rotation. Winners are never trimmed for being up.

7. EXITS, checked every session: -12% hard stop from average cost (fast, small
   losses); an ATR trail at trail_k x ATR% below the highest close seen while
   held, bounded [12%, 30%] (wide on purpose — the trail protects compounders,
   it does not harvest them); a trend break after 5 consecutive closes under
   sma50; rank decay on scheduled rebalances.

8. ADAPT (every 63 sessions, deterministic and bounded). The realised window is
   back-propagated into the ramp endpoints, the exposure scalar, the override
   triggers, the stop geometry, the churn cadence and the momentum horizon
   weights. Every dial is FIRST pulled 15% of the way back to its structural
   default: an adaptation survives only while the evidence keeps repeating, so
   no parameter can ratchet to its bound over a long one-way stretch and quietly
   turn this into a different strategy. Every change is reported for audit.

No hardcoded dates, no per-ticker plans, no memorised tape. Deterministic,
stdlib only, no IO, NaN-guarded throughout.
"""

from __future__ import annotations

try:                                   # the arena's base class when run by the engine
    from strategy_base import Strategy
except Exception:                      # stand-alone import: keep the contract shape
    class Strategy:                    # pragma: no cover
        meta = {}

        def decide(self, date, view, portfolio, ctx):
            raise NotImplementedError

        def adapt(self, feedback):
            return None

# --- structural constants (not adapted; these are the shape of the desk) ----
MIN_LIQ_ABS = 10_000_000.0   # $ 20-day average dollar turnover floor
LIQ_REL = 0.10               # ... and at least this fraction of the universe median
PX_MIN = 5.0
ATR_MAX = 0.10
RSI_MAX = 93.0
MIN_ORDER = 2_000.0
CASH_BUF = 0.004
REENTRY_COOL = 8
MAX_NEW_PER_DAY = 3
MAX_NEW_RAMP = 5             # when the book is far below target, deploy faster
REBAL_BAND_UP = 0.05         # gross below target by this much -> rebalance
REBAL_BAND_DN = 0.06         # gross above target by this much -> de-risk now
ADD_BAND = 0.02              # new name: underweight worth an order
ADD_HELD_FRAC = 0.30         # top-up a live line only if this far under target
ADD_MIN_EQ = 0.015           # ... and only for a ticket worth this much of equity
TRIM_BAND = 0.05             # per-name overweight worth an order (wide: winners run)
DECAY = 0.15                 # adapt(): pull-back to structural defaults per window
VOL_FLOOR = 0.18
BREADTH_HIST = 40
SMA_GAPS = ((("sma20"), 0.020, 0.20), (("sma50"), 0.035, 0.30),
            (("sma100"), 0.055, 0.25), (("sma200"), 0.080, 0.25))
DEFENSIVE = ("Health Care", "Healthcare", "Consumer Staples", "Utilities",
             "Telecommunications", "Consumer Defensive")


def _ok(x):
    return isinstance(x, (int, float)) and x == x and abs(x) != float("inf")


def _f(x, d=0.0):
    return float(x) if _ok(x) else d


def _clip(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _pct_ranks(pairs):
    """[(code, value)] -> {code: percentile in [0,1]}. Deterministic ties."""
    s = sorted(pairs, key=lambda t: (t[1], t[0]))
    n = len(s)
    if n <= 1:
        return {c: 0.5 for c, _ in s}
    inv = 1.0 / (n - 1)
    return {c: i * inv for i, (c, _) in enumerate(s)}


class RegimeRotation(Strategy):
    meta = {
        "handle": "regime",
        "name": "Regime",
        "style": ("Four-signal regime score sets a quantised exposure rung; "
                  "momentum/sector rotation fills it; overrides fire same-session."),
        "risk_style": "adaptive exposure, trend rotation, wide trails on winners",
        "color": "#888888",
        "param_space": {
            "ramp_lo": [-0.60, -0.10],
            "ramp_hi": [0.00, 0.40],
            "gross_floor": [0.20, 0.70],
            "exposure_scale": [0.70, 1.12],
            "panic_ret": [-0.040, -0.012],
            "panic_breadth": [0.30, 0.58],
            "thrust_hi": [0.50, 0.70],
            "eq_stop_dd": [-0.22, -0.06],
            "hard_stop": [-0.20, -0.07],
            "trail_k": [2.4, 5.6],
            "w_m1": [0.04, 0.45],
            "w_m3": [0.08, 0.50],
            "w_m6": [0.08, 0.50],
            "w_m12": [0.04, 0.50],
            "rebal_every": [6, 18],
        },
    }

    def __init__(self):
        self.P = {
            # regime model
            "w_trend": 0.34, "w_breadth": 0.28, "w_mom": 0.12, "w_stress": 0.26,
            "b_mid": 0.50, "b_div": 0.16, "b_slope_div": 0.07,
            "mom_div1": 0.045, "mom_div3": 0.085,
            "vol_div": 0.60, "dd_div": 0.13, "streak_div": 4.0,
            # exposure
            "ramp_lo": -0.32, "ramp_hi": 0.16, "gross_floor": 0.42,
            "exposure_scale": 1.0, "gross_step": 0.25,
            "up_band": 0.09, "down_band": 0.09,
            # overrides
            "panic_ret": -0.023, "panic_breadth": 0.46,
            "panic_gross": 0.35, "panic_days": 3,
            "thrust_lo": 0.34, "thrust_hi": 0.58, "thrust_win": 20,
            "thrust_hold": 25, "thrust_cool": 40,
            "eq_stop_dd": -0.13, "eq_stop_gross": 0.55, "eq_stop_clear": 0.10,
            # book
            "max_names": 14, "max_w": 0.13, "max_per_sector": 6,
            "hold_buffer": 24, "rebal_every": 13,
            # selection
            "w_m1": 0.12, "w_m3": 0.26, "w_m6": 0.34, "w_m12": 0.28,
            "hi_bonus": 0.30, "rs_w": 0.15, "sec_tilt": 0.18, "def_tilt": 0.20,
            "vol_pow": 0.5,
            # exits
            "hard_stop": -0.12, "trail_k": 3.6,
            "trail_min": 0.12, "trail_max": 0.30, "break_days": 5,
        }
        self._P0 = dict(self.P)   # structural defaults; adapt decays back toward these
        self._breadth_hist = []
        self._vol_ema = None
        self._down_streak = 0
        self._prev_ix = None
        self._gross = 0.0
        self._eq_peak = 0.0
        self._peak = {}          # code -> highest raw close since entry
        self._below = {}         # code -> consecutive closes under sma50
        self._cool = {}          # code -> day until re-entry is barred
        self._ordered = {}       # code -> day an order was queued (dupe guard)
        self._last_rank = {}     # code -> rank position at last full ranking
        self._panic_until = -1
        self._thrust_until = -1
        self._thrust_last = -999
        self._eq_stop = False
        self._last_rung = None
        self._n_adapt = 0

    # ------------------------------------------------------------- regime
    def _regime_score(self, ix, breadth):
        P = self.P
        c = ix.get("AdjClose")
        # trend: normalised gaps to four averages
        trend, tw = 0.0, 0.0
        if _ok(c) and c > 0:
            for key, div, w in SMA_GAPS:
                s = ix.get(key)
                if _ok(s) and s > 0:
                    trend += w * _clip((c / s - 1.0) / div, -1.0, 1.0)
                    tw += w
        trend = trend / tw if tw > 0 else 0.0

        # breadth: level + slope of participation
        self._breadth_hist.append(breadth)
        if len(self._breadth_hist) > BREADTH_HIST:
            self._breadth_hist.pop(0)
        h = self._breadth_hist
        lvl = _clip((breadth - P["b_mid"]) / P["b_div"], -1.0, 1.0)
        if len(h) >= 20:
            slope = sum(h[-5:]) / 5.0 - sum(h[-20:]) / 20.0
            slp = _clip(slope / P["b_slope_div"], -1.0, 1.0)
        else:
            slp = 0.0
        bread = 0.65 * lvl + 0.35 * slp

        # momentum
        m1 = _clip(_f(ix.get("ret_1m")) / P["mom_div1"], -1.0, 1.0)
        m3 = _clip(_f(ix.get("ret_3m")) / P["mom_div3"], -1.0, 1.0)
        mom = 0.5 * m1 + 0.5 * m3

        # stress (0..1, subtractive)
        v = ix.get("vol_21")
        if _ok(v) and v > 0:
            self._vol_ema = v if self._vol_ema is None else self._vol_ema * 0.99 + v * 0.01
        s1 = 0.0
        if _ok(v) and self._vol_ema and self._vol_ema > 0:
            s1 = _clip((v / self._vol_ema - 1.0) / P["vol_div"], 0.0, 1.0)
        d52 = ix.get("dist_52w_high")
        s2 = _clip(-_f(d52) / P["dd_div"], 0.0, 1.0) if _ok(d52) else 0.0
        s3 = _clip(self._down_streak / P["streak_div"], 0.0, 1.0)
        stress = 0.35 * s1 + 0.45 * s2 + 0.20 * s3

        score = (P["w_trend"] * trend + P["w_breadth"] * bread
                 + P["w_mom"] * mom - P["w_stress"] * stress)
        return _clip(score, -1.0, 1.0), trend, bread, stress

    def _target_gross(self, score, day, breadth, bret, own_dd, ix):
        """Quantised exposure rung + same-session overrides. Returns (gross, tag)."""
        P = self.P
        lo, hi = P["ramp_lo"], P["ramp_hi"]
        if hi - lo < 0.15:
            hi = lo + 0.15
        t = _clip((score - lo) / (hi - lo), 0.0, 1.0)
        floor = P["gross_floor"]
        raw = (floor + (1.0 - floor) * t) * P["exposure_scale"]
        raw = _clip(raw, floor, 1.0)

        step = P["gross_step"]
        cur = self._gross
        if cur <= 0.0 or raw > cur + P["up_band"] or raw < cur - P["down_band"]:
            rung = round(raw / step) * step
            rung = _clip(rung, floor if raw > 0.02 else 0.0, 1.0)
        else:
            rung = cur

        tag = ""
        # --- thrust: participation vaults off a washed-out base
        h = self._breadth_hist
        w = int(P["thrust_win"])
        if (len(h) > w and breadth >= P["thrust_hi"]
                and min(h[-w:]) <= P["thrust_lo"]
                and day - self._thrust_last > P["thrust_cool"]):
            self._thrust_until = day + int(P["thrust_hold"])
            self._thrust_last = day
            self._eq_stop = False
            tag = "thrust"
        if day <= self._thrust_until:
            # a thrust that cannot hold the index's own 20-day line was a bounce
            c20, s20 = ix.get("AdjClose"), ix.get("sma20")
            if _ok(c20) and _ok(s20) and c20 < s20 and tag != "thrust":
                self._thrust_until = day - 1
            else:
                rung = max(rung, 1.0)
                tag = tag or "thrust"

        # --- equity stop: my own curve is a regime signal
        if own_dd <= P["eq_stop_dd"]:
            self._eq_stop = True
        if self._eq_stop:
            if score >= P["eq_stop_clear"] and own_dd > P["eq_stop_dd"] * 0.5:
                self._eq_stop = False
            else:
                rung = min(rung, P["eq_stop_gross"])
                tag = "equity-stop"

        # --- circuit breaker: air pocket on thin participation
        if bret <= P["panic_ret"] and breadth < P["panic_breadth"]:
            self._panic_until = day + int(P["panic_days"])
            tag = "circuit-breaker"
        if day <= self._panic_until:
            rung = min(rung, P["panic_gross"])
            tag = tag or "circuit-breaker"

        self._gross = rung
        return rung, tag

    # ---------------------------------------------------------- selection
    def _rank(self, view, sectors, gross, pos, day, peer_w):
        P = self.P
        rows, liq = [], []
        for c, r in view.items():
            if c == "IXIC":
                continue
            px = r.get("Close")
            if not _ok(px) or px < PX_MIN:
                continue
            vs = r.get("vol_sma20")
            if not _ok(vs) or vs <= 0:
                continue
            dol = vs * px
            liq.append(dol)
            r3 = r.get("ret_3m")
            r6 = r.get("ret_6m")
            s50, s100 = r.get("sma50"), r.get("sma100")
            a = r.get("AdjClose")
            if not (_ok(r3) and _ok(r6) and _ok(a) and _ok(s50) and _ok(s100)):
                continue
            rows.append((c, r, dol, a, s50, s100, r3, r6))
        if not rows:
            return [], {}
        liq.sort()
        med = liq[len(liq) // 2]
        liq_bar = max(MIN_LIQ_ABS, LIQ_REL * med)

        cands = []
        for c, r, dol, a, s50, s100, r3, r6 in rows:
            if dol < liq_bar:
                continue
            if a <= s50 or a <= s100:
                continue
            if r3 <= 0.0:
                continue
            ap = r.get("atr_pct")
            if _ok(ap) and ap > ATR_MAX:
                continue
            rsi = r.get("rsi14")
            if _ok(rsi) and rsi > RSI_MAX and c not in pos:
                continue
            cands.append((c, r, r3, r6))
        if not cands:
            return [], {}

        # risk-adjusted momentum percentiles
        p1, p3, p6, p12, phi, prs, plv = [], [], [], [], [], [], []
        for c, r, r3, r6 in cands:
            v = r.get("vol_21")
            v = v if (_ok(v) and v > 0) else 0.35
            damp = (VOL_FLOOR + v) ** P["vol_pow"]
            p1.append((c, _f(r.get("ret_1m")) / damp))
            p3.append((c, r3 / damp))
            p6.append((c, r6 / damp))
            r12 = r.get("ret_12m")
            p12.append((c, (r12 / damp) if _ok(r12) else None))
            phi.append((c, _f(r.get("dist_52w_high"), -0.35)))
            prs.append((c, _f(r.get("rs_bench_3m"))))
            plv.append((c, -v))
        R1 = _pct_ranks(p1)
        R3 = _pct_ranks(p3)
        R6 = _pct_ranks(p6)
        have12 = [(c, v) for c, v in p12 if v is not None]
        R12 = _pct_ranks(have12)
        RH = _pct_ranks(phi)
        RS = _pct_ranks(prs)
        RV = _pct_ranks(plv)

        wsum = P["w_m1"] + P["w_m3"] + P["w_m6"] + P["w_m12"]
        wsum = wsum if wsum > 0 else 1.0
        base = {}
        for c, r, r3, r6 in cands:
            # young listings: shrink the missing 12m read toward neutral
            b12 = R12.get(c)
            if b12 is None:
                b12 = 0.5 * R6[c] + 0.25
            b = (P["w_m1"] * R1[c] + P["w_m3"] * R3[c]
                 + P["w_m6"] * R6[c] + P["w_m12"] * b12) / wsum
            base[c] = b

        # sector rotation: rank sectors on their members' own base scores
        buckets = {}
        for c, r, r3, r6 in cands:
            buckets.setdefault(sectors.get(c, "Other"), []).append(base[c])
        sec_pairs = []
        for s, vals in buckets.items():
            vals.sort()
            sec_pairs.append((s, vals[len(vals) // 2]))
        SEC = _pct_ranks(sec_pairs)

        risk_off = _clip(1.0 - gross, 0.0, 1.0)
        scored = []
        for c, r, r3, r6 in cands:
            sc = base[c]
            sc += P["hi_bonus"] * (RH[c] - 0.5)
            sc += P["rs_w"] * (RS[c] - 0.5)
            sc += P["sec_tilt"] * (SEC.get(sectors.get(c, "Other"), 0.5) - 0.5)
            if risk_off > 0:
                sc += P["def_tilt"] * risk_off * (RV[c] - 0.5)
                if sectors.get(c, "") in DEFENSIVE:
                    sc += 0.06 * risk_off
            pw = peer_w.get(c)
            if pw:
                sc += min(0.05, 0.25 * pw)
            scored.append((sc, c, r))
        scored.sort(key=lambda t: (-t[0], t[1]))
        ranks = {c: i for i, (sc, c, r) in enumerate(scored)}
        self._last_rank = ranks
        return scored, ranks

    # ------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        P = self.P
        day = int(ctx.get("day_index", 0))
        pos = portfolio.get("positions") or {}
        cash = float(_f(portfolio.get("cash"), 0.0))
        eq = float(_f(portfolio.get("equity"), 0.0)) or 1.0
        sectors = ctx.get("sectors") or {}
        breadth = _f(ctx.get("breadth_sma50"), 0.5)
        bret = _f(ctx.get("tasi_ret_1d"), 0.0)
        ix = view.get("IXIC") or {}

        self._down_streak = self._down_streak + 1 if bret < 0 else 0
        self._eq_peak = max(self._eq_peak, eq)
        own_dd = (eq / self._eq_peak - 1.0) if self._eq_peak > 0 else 0.0

        score, trend, bread, stress = self._regime_score(ix, breadth)
        prev_rung = self._gross
        gross_t, tag = self._target_gross(score, day, breadth, bret, own_dd, ix)

        orders, notes = [], []
        sold = set()

        # ------------------------------------------------------ exits first
        for c, ph in pos.items():
            r = view.get(c)
            if r is None:
                continue
            px = r.get("Close")
            if not _ok(px) or px <= 0:
                continue
            self._peak[c] = max(self._peak.get(c, px), px)
            up = _f(ph.get("unrealized_pct"), 0.0)
            a, s50 = r.get("AdjClose"), r.get("sma50")
            if _ok(a) and _ok(s50):
                self._below[c] = self._below.get(c, 0) + 1 if a < s50 else 0
            reason = None
            if up <= P["hard_stop"]:
                reason = f"hard stop {up:+.1%} — small loss, taken now"
            if reason is None:
                ap = r.get("atr_pct")
                ap = ap if (_ok(ap) and ap > 0) else 0.03
                tr = _clip(P["trail_k"] * ap, P["trail_min"], P["trail_max"])
                pk = self._peak.get(c, px)
                if pk > 0 and px <= pk * (1.0 - tr):
                    reason = (f"trail {tr:.0%} off the {pk:.2f} peak; "
                              f"booked {up:+.1%}")
            if reason is None and self._below.get(c, 0) >= int(P["break_days"]):
                reason = f"trend break: {int(P['break_days'])} closes under sma50"
            if reason:
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sold.add(c)
                self._cool[c] = day + REENTRY_COOL
                if abs(up) >= 0.15:
                    notes.append(f"exit {c} {up:+.0%}: {reason}")

        for c in list(self._peak):
            if c not in pos:
                self._peak.pop(c, None)
                self._below.pop(c, None)

        held = {c: ph for c, ph in pos.items() if c not in sold}
        held_val = sum(_f(ph.get("value")) for ph in held.values())
        gross_now = held_val / eq if eq > 0 else 0.0

        # ------------------------------------------------- rebalance to plan
        # One target book, one set of target weights. The rung sets HOW MUCH,
        # the ranking sets WHICH; nothing else moves the book.
        drift = gross_t - gross_now
        rebal_due = (day % max(1, int(P["rebal_every"])) == 0)
        run = rebal_due or drift > REBAL_BAND_UP or drift < -REBAL_BAND_DN
        if run:
            scored, ranks = self._rank(view, sectors, gross_t, pos, day,
                                       self._peer_weights(ctx))
            n_book = int(round(P["max_names"] * (0.45 + 0.55 * gross_t)))
            n_book = max(4, min(int(P["max_names"]), n_book))
            limit = int(P["max_names"]) + int(P["hold_buffer"])
            rowof = {c: r for sc, c, r in scored}
            sec_cap = int(P["max_per_sector"])

            # 1. keepers — held names still inside the hysteresis buffer.
            #    Rank decay is only judged on a scheduled rebalance: an
            #    off-cycle top-up must never turn into a rotation.
            book, sec_n = [], {}
            n_keep = n_book if rebal_due else int(P["max_names"])
            for c in sorted(held, key=lambda x: (ranks.get(x, 10 ** 6), x)):
                if len(book) >= n_keep:
                    break
                if rebal_due and ranks.get(c, 10 ** 6) > limit:
                    continue
                s = sectors.get(c, "Other")
                if sec_n.get(s, 0) >= sec_cap:
                    continue
                book.append(c)
                sec_n[s] = sec_n.get(s, 0) + 1

            # 2. new risk — only when the breaker is not live
            if day > self._panic_until and drift > -REBAL_BAND_DN:
                n_new = MAX_NEW_RAMP if drift > 0.30 else MAX_NEW_PER_DAY
                added = 0
                for sc, c, r in scored:
                    if len(book) >= n_book or added >= n_new:
                        break
                    if c in pos or c in sold:
                        continue
                    if day <= self._cool.get(c, -1):
                        continue
                    if day - self._ordered.get(c, -999) <= 3:
                        continue
                    s = sectors.get(c, "Other")
                    if sec_n.get(s, 0) >= sec_cap:
                        continue
                    book.append(c)
                    sec_n[s] = sec_n.get(s, 0) + 1
                    added += 1

            # 3. inverse-volatility target weights, normalised to the rung
            raw = {}
            for c in book:
                r = rowof.get(c) or view.get(c) or {}
                v = r.get("vol_21")
                v = v if (_ok(v) and v > 0) else 0.35
                raw[c] = 1.0 / max(VOL_FLOOR, v)
            tot = sum(raw.values())
            tw = {}
            if tot > 0:
                for c in book:
                    tw[c] = min(P["max_w"], gross_t * raw[c] / tot)
                short = gross_t - sum(tw.values())
                if short > 0.005:
                    free = [c for c in book if tw[c] < P["max_w"] - 1e-9]
                    fw = sum(raw[c] for c in free)
                    if fw > 0:
                        for c in free:
                            tw[c] = min(P["max_w"], tw[c] + short * raw[c] / fw)

            # 4. release what the plan no longer holds
            cutting = drift < -REBAL_BAND_DN
            for c in list(held):
                if c in book or c in sold:
                    continue
                if not (rebal_due or cutting):
                    continue
                why = ("exposure cut to %.0f%% (%s)" % (gross_t * 100, tag)
                       if cutting else "rank decay: out of the rotation")
                orders.append({"code": c, "side": "sell", "all": True, "reason": why})
                sold.add(c)
                self._cool[c] = day + 3

            # 5. trims and adds toward the plan (sells first: their proceeds
            #    settle at the same open, so a rotation clears in one session)
            proceeds = sum(_f(pos[c].get("value")) for c in sold if c in pos) * 0.985
            avail = max(0.0, cash * (1.0 - CASH_BUF) + proceeds)
            for c in book:
                ph = held.get(c)
                cur_w = _f(ph.get("weight")) if ph else 0.0
                d = tw.get(c, 0.0) - cur_w
                band = (ADD_BAND if ph is None
                        else max(ADD_BAND, ADD_HELD_FRAC * tw.get(c, 0.0)))
                if d > band and avail >= MIN_ORDER:
                    amt = min(d * eq, avail)
                    if amt >= max(MIN_ORDER, ADD_MIN_EQ * eq):
                        orders.append({"code": c, "side": "buy", "sar": round(amt, 2),
                                       "reason": ("rotation: rank %d, target %.0f%% of book, "
                                                  "gross %.0f%%" % (ranks.get(c, 0) + 1,
                                                                    tw.get(c, 0.0) * 100,
                                                                    gross_t * 100))})
                        self._ordered[c] = day
                        if ph is None:
                            px0 = (rowof.get(c) or view.get(c) or {}).get("Close")
                            self._peak[c] = _f(px0, 0.0)
                            self._below[c] = 0
                        avail -= amt
                elif (ph is not None and d < -TRIM_BAND and cur_w > 0
                      and (rebal_due or cutting)):
                    frac = _clip(-d / cur_w, 0.0, 0.6)
                    if frac * _f(ph.get("value")) >= MIN_ORDER:
                        orders.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                       "reason": "trim to %.0f%% target (gross %.0f%%)"
                                                 % (tw.get(c, 0.0) * 100, gross_t * 100)})

        # -------------------------------------------------- sentiment / note
        sent = _clip(1.15 * score + 0.25 * (breadth - 0.5) * 2.0, -1.0, 1.0)
        mood = ("risk-off" if gross_t <= 0.3 else
                "defensive" if gross_t <= 0.55 else
                "constructive" if gross_t < 1.0 else "risk-on")
        note = ""
        if tag and tag != self._last_rung:
            note = (f"{tag}: regime {score:+.2f} (trend {trend:+.2f}, breadth "
                    f"{bread:+.2f}, stress {stress:.2f}) -> gross {gross_t:.0%}.")
        elif abs(gross_t - prev_rung) > 1e-9:
            note = (f"exposure rung {prev_rung:.0%} -> {gross_t:.0%} on regime "
                    f"{score:+.2f} (breadth {breadth:.0%}).")
        elif notes:
            note = notes[0]
        self._last_rung = tag

        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood,
                "note": note}

    # ----------------------------------------------------------- peers
    def _peer_weights(self, ctx):
        peers = ctx.get("peers") or {}
        if not peers:
            return {}
        rows = []
        for h, v in peers.items():
            if isinstance(v, dict):
                rows.append((_f(v.get("ret_63")), str(h), v))
        if not rows:
            return {}
        rows.sort(key=lambda t: (-t[0], t[1]))
        out = {}
        for r63, _h, v in rows[:max(1, len(rows) // 3)]:
            if r63 <= 0:
                continue
            for c, w in (v.get("positions") or {}).items():
                if _ok(w):
                    out[c] = out.get(c, 0.0) + float(w)
        return out

    # ----------------------------------------------------------- adapt
    def adapt(self, feedback):
        """Back-propagate the realised window into the dials. Bounded, small,
        deterministic; every parameter is clamped into meta['param_space']."""
        P = self.P
        sp = self.meta["param_space"]
        w = (feedback or {}).get("window") or {}
        cum = (feedback or {}).get("cumulative") or {}
        trades = (feedback or {}).get("trades") or []
        self._n_adapt += 1

        ret = _f(w.get("ret"))
        bench = _f(w.get("bench_ret"))
        sharpe = _f(w.get("sharpe"))
        mdd = _f(w.get("max_dd"))
        expo = _f(w.get("avg_exposure"), 0.5)
        turn = _f(w.get("turnover"))
        n_sells = int(_f(w.get("n_sells")))
        hit = w.get("hit_rate")
        pf = w.get("profit_factor")
        edge = ret - bench
        before = {k: P[k] for k in sp}

        # LEAKY INTEGRATOR. Every dial is first pulled a fraction of the way
        # back to its structural default. An adaptation therefore survives only
        # while the evidence keeps repeating: no dial can ratchet to its bound
        # over a long one-way stretch and quietly become a different strategy.
        for k in sp:
            P[k] = P[k] + DECAY * (self._P0[k] - P[k])

        def bump(key, delta):
            lo, hi = sp[key]
            P[key] = _clip(P[key] + delta, lo, hi)

        # 1) exposure scalar tracks the Sharpe the book actually realised
        if sharpe >= 1.0 and ret > 0:
            bump("exposure_scale", 0.03)
        elif sharpe <= 0.0 or mdd <= -0.18:
            bump("exposure_scale", -0.05)
        elif sharpe < 0.35:
            bump("exposure_scale", -0.02)

        # 2) ramp endpoints: which way did the regime gate cost money?
        if bench >= 0.04 and edge < -0.02 and expo < 0.85:
            bump("ramp_lo", -0.02)          # invest sooner, we sat out a rally
            bump("ramp_hi", -0.02)
            bump("gross_floor", 0.02)
        elif bench <= -0.04 and edge < 0.01 and expo > 0.55:
            bump("ramp_lo", 0.02)           # de-risk sooner, we rode a decline
            bump("ramp_hi", 0.02)
            bump("gross_floor", -0.02)
        if P["ramp_hi"] < P["ramp_lo"] + 0.15:
            bump("ramp_hi", P["ramp_lo"] + 0.15 - P["ramp_hi"])

        # 3) stop geometry from hit-rate / profit-factor drift
        if hit is not None and n_sells >= 6:
            hr = _f(hit, 0.5)
            pfv = _f(pf, 1.0) if pf is not None else 1.0
            if hr < 0.40 and pfv < 1.3:
                bump("hard_stop", -0.01)     # stopped out of noise: more room
                bump("trail_k", 0.15)
            elif hr > 0.60 and pfv < 1.6:
                bump("hard_stop", 0.01)      # losers too big for the winners
                bump("trail_k", -0.15)

        # 4) momentum horizon weights follow the trades that actually paid
        short_p, short_n, long_p, long_n = 0.0, 0, 0.0, 0
        for t in trades:
            hs = t.get("held_since")
            pnl = _f(t.get("realized_pnl"))
            if not isinstance(hs, str) or len(hs) < 10:
                continue
            try:
                y0, m0, d0 = int(hs[0:4]), int(hs[5:7]), int(hs[8:10])
                ds = str(feedback.get("date", ""))
                y1, m1, d1 = int(ds[0:4]), int(ds[5:7]), int(ds[8:10])
            except (ValueError, TypeError):
                continue
            days = (y1 - y0) * 365 + (m1 - m0) * 30 + (d1 - d0)
            if days <= 60:
                short_p += pnl
                short_n += 1
            else:
                long_p += pnl
                long_n += 1
        if short_n >= 3 and long_n >= 3:
            sa = short_p / short_n
            la = long_p / long_n
            if sa > la:
                bump("w_m1", 0.02)
                bump("w_m3", 0.01)
                bump("w_m12", -0.02)
            elif la > sa:
                bump("w_m12", 0.02)
                bump("w_m6", 0.01)
                bump("w_m1", -0.02)

        # 5) override triggers follow realised drawdown
        if mdd <= -0.15:
            bump("eq_stop_dd", 0.01)         # tighter own-equity brake
            bump("panic_ret", 0.001)         # breaker fires a touch more easily
            bump("thrust_hi", -0.01)         # and re-arms a touch sooner
        elif mdd > -0.05 and edge < 0.0:
            bump("eq_stop_dd", -0.01)        # brakes were costing performance
            bump("panic_ret", -0.001)
            bump("thrust_hi", 0.01)

        # 6) churn control
        pfv = _f(pf, 1.0) if pf is not None else 1.0
        if turn > 6.0 and pfv < 1.4:
            bump("rebal_every", 1)
        elif turn < 1.5 and edge < 0.0:
            bump("rebal_every", -1)
        P["rebal_every"] = int(round(P["rebal_every"]))

        # momentum weights are a mix: keep them summing to one
        tot = P["w_m1"] + P["w_m3"] + P["w_m6"] + P["w_m12"]
        if tot > 0:
            for k in ("w_m1", "w_m3", "w_m6", "w_m12"):
                P[k] = _clip(P[k] / tot, *sp[k])

        changes = {k: round(P[k], 4) for k in sp
                   if abs(P[k] - before[k]) > 5e-4}

        note = (f"w{self._n_adapt}: ret {ret:+.1%} vs bench {bench:+.1%}, "
                f"sharpe {sharpe:.2f}, dd {mdd:.1%}, exposure {expo:.0%}, "
                f"turnover {turn:.1f}x -> "
                + (", ".join(f"{k}={v}" for k, v in sorted(changes.items()))
                   if changes else "dials already where the tape wants them")
                + f"; equity {_f(cum.get('equity')):,.0f}")
        return {"changes": changes, "note": note}


STRATEGY = RegimeRotation()
