"""factor — multi-factor systematic desk for the AAOIFI-screened NASDAQ universe.

THESIS
------
No single anomaly survives a regime change intact; a *blend* of orthogonal,
documented cross-sectional factors does. The whole book is therefore one
composite z-score, re-derived from scratch out of five sleeves — nothing in it
is a memorised name, a date, or a price level:

  TREND      price vs its 200d, and the 50d/200d alignment   (trend quality)
  MOM_FAST   3-month return + 3-month relative strength vs IXIC
  MOM_SLOW   6-month and 12-minus-1-month return             (Jegadeesh-Titman)
  LOWVOL     inverse realised vol and inverse ATR%           (low-risk anomaly)
  REVERSAL   negative 1-week / 1-day return                  (buy the pullback)

TREND and MOM measure *whether* a name is winning; REVERSAL decides *when* to
pay for it; LOWVOL is the risk-control diversifier. Every sleeve is a rank
statistic (robust median/MAD z, clipped at +/-3), so the score means the same
thing in any market, at any price level, in any volatility regime — which is the
whole point when the evaluation data does not exist yet.

The only thing that decides how much each sleeve matters is `adapt()`, which
back-propagates realised trade P&L onto the sleeve z-scores that were true at
entry. Priors are deliberately broad and non-committal; the loop does the work.

THE RULEBOOK
------------
1. ELIGIBILITY (re-derived every session, never a fixed list): 20-day EMA of
   dollar turnover >= $20M — a liquidity floor, not a size bet; price >= $5;
   0.6% <= ATR% <= 12%; and a complete indicator row, which requires 12 months
   of history (no IPO lottery tickets).
2. SCORE = sum(w_sleeve * z_sleeve) across the eligible cross-section, weights
   normalised at use time. The sleeve weights are the adaptive parameters.
3. ENTRY GATE, structural: a *new* name must trade above its own 200-day
   average. Factor rank orders the uptrending cohort; it never licenses catching
   a falling knife.
4. BOOK: the top N_POS names, conviction-tilted by rank with a mild inverse-vol
   adjustment, a single-name cap, and never more than half the slots in one
   sector — leadership overweight is allowed, a monoculture is not. Reviewed
   every 5 sessions (or sooner if an exit has left >20% of the book in idle
   cash). Hysteresis — a holding is kept while it stays inside the top
   2.5 x N_POS and for at least MIN_HOLD sessions — is what makes this a
   portfolio rather than a weekly lottery. Positions are never rebalanced back
   *down* to their entry weight: a winner is allowed to grow into a larger share
   of the book and is only trimmed for a cap breach or to bring total gross back
   to target. Trimming winners weekly is a tax on the only trades that matter.
5. GROSS = min(1, regime dial x vol-target scale) x own-drawdown scaler. The
   regime dial is *continuous* in IXIC-vs-its-200d and market breadth, with a
   floor, because the single most expensive mistake of the previous experiment
   was a binary regime switch that fired cleanly in-sample and chopped out of
   it. The vol-target scale de-levers when the book's own estimated volatility
   runs above target — automatic crash protection that needs no forecast.
6. EXITS, asymmetric and few: a wide disaster stop (insurance against a single
   idiosyncratic collapse, not a trading rule), a wide ATR trail on names that
   have already run, a trend break only when the position is under water, and
   the natural factor exit — falling out of the extended ranking. Deliberately
   sparse: in a rank-driven book, tight stops just pay the spread to re-buy the
   same name a week later.
7. adapt(): every 63 sessions I hold, for every trade closed in the window, the
   sleeve z-vector as of entry and its realised return. The covariance between
   each sleeve's entry z and trade return is a gradient; sleeve weights move
   multiplicatively along it, bounded and clamped. Exposure follows realised
   Sharpe, the stop follows hit-rate, the trail and book breadth follow profit
   factor. Deterministic, small steps, no lookahead, fully audited.

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
GROSS_FLOOR = 0.55         # the regime dial never takes the book below this

# ---------------------------------------------------------------- exits
TRAIL_ARM = 0.25           # the trail arms only after a real run
VSCALE_FLOOR = 0.35

# ---------------------------------------------------------------- adapt
LR_SLEEVE = 0.22           # multiplicative step on sleeve weights
MIN_ATTRIB = 6             # closed trades needed before touching sleeve weights
HIT_TARGET = 0.45
PF_TARGET = 1.5

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


class Factor(Strategy):
    meta = {
        "handle": "factor",
        "name": "Factor",
        "style": ("Cross-sectional multi-factor blend — trend quality, fast and slow momentum, "
                  "low volatility, short-term reversal — held as a concentrated conviction-weighted "
                  "book with vol-targeted gross; adapt() back-propagates realised trade P&L onto "
                  "the sleeve weights."),
        "risk_style": "systematic multi-factor, vol-targeted",
        "color": "#888888",
        "param_space": {
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
        },
    }

    def __init__(self):
        # adaptive parameters — every one bounded by meta["param_space"]
        self.p = {
            "W_TREND": 0.28,
            "W_MOM_FAST": 0.14,
            "W_MOM_SLOW": 0.28,
            "W_LOWVOL": 0.12,
            "W_REVERSAL": 0.22,
            "TARGET_VOL": 0.46,
            "N_POS": 10.0,
            "STOP_LOSS": 0.25,
            "TRAIL_ATR": 7.0,
            "MAX_W": 0.18,
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

        self._eq_peak = max(self._eq_peak, eq)
        own_dd = (eq / self._eq_peak - 1.0) if self._eq_peak > 0 else 0.0

        # --- continuous regime dial (never a binary switch)
        ix = view.get("IXIC") or {}
        ic, i200, i50 = ix.get("AdjClose"), ix.get("sma200"), ix.get("sma50")
        if _ok(ic) and _ok(i200) and i200 > 0:
            reg_t = _clamp((ic / i200 - 1.0 + 0.04) / 0.10, 0.0, 1.0)
        else:
            reg_t = 0.7
        if _ok(ic) and _ok(i50) and i50 > 0:
            reg_t = 0.75 * reg_t + 0.25 * _clamp((ic / i50 - 1.0 + 0.03) / 0.06, 0.0, 1.0)
        reg_b = _clamp((breadth - 0.30) / 0.35, 0.0, 1.0)
        regime = GROSS_FLOOR + (1.0 - GROSS_FLOOR) * (0.65 * reg_t + 0.35 * reg_b)
        dd_mult = _clamp(1.0 + (own_dd + 0.18) * 1.6, 0.60, 1.0)

        orders, sells, notes = [], set(), []

        # ------------------------------------------------------ daily exits
        stop_loss = float(self.p["STOP_LOSS"])
        trail_atr = float(self.p["TRAIL_ATR"])
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
            elif (_ok(px) and _ok(pk) and _ok(atr) and atr > 0 and up >= TRAIL_ARM
                  and px <= pk - trail_atr * atr):
                reason = f"trail: {trail_atr:.1f}x ATR off the peak, banked {up:+.1%}"
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
        due = (day - self._last_rebal >= REBAL_EVERY) or \
              (cash_frac > CASH_TRIGGER and day - self._last_rebal >= 2)
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
                # 2. fill the remaining slots from the top of the ranking
                new_n = 0
                sec_cap = max(3, int(SECTOR_FRAC * n_pos))
                sec_n = {}
                for _, c, _ in targets:
                    k_ = sectors.get(c, "Other")
                    sec_n[k_] = sec_n.get(k_, 0) + 1
                if len(targets) < n_pos:
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
                    # 4. vol target -> gross exposure
                    sig = sum(base[c] * max(0.10, float(t[3])) for _, c, t in targets)
                    est = sig * math.sqrt(RHO + (1.0 - RHO) / k)
                    vscale = _clamp(float(self.p["TARGET_VOL"]) / est, VSCALE_FLOOR, 1.0) \
                        if est > 1e-6 else 1.0
                    gross = _clamp(regime * vscale, 0.0, 1.0) * dd_mult * MAX_GROSS
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
                        orders.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                       "reason": f"trim {frac:.0%}: cap / gross target"})
                        proceeds += cut * eq

                # 6. buys, best score first
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
        if notes:
            note = notes[0]
        elif self._reg_bucket is not None and bucket != self._reg_bucket:
            note = (f"regime dial {regime:.2f} (IXIC trend {reg_t:.2f}, breadth {breadth:.0%}) "
                    f"— target gross moves with it")
        self._reg_bucket = bucket

        sent = _clamp(2.2 * (regime - 0.78) + 1.2 * (breadth - 0.5) + 4.0 * own_dd, -1.0, 1.0)
        sent = 0.5 * self._sent_prev + 0.5 * sent
        self._sent_prev = sent
        out = {"orders": orders, "sentiment": round(sent, 2)}
        if note:
            out["note"] = note
        return out

    # --------------------------------------------------------------- adapt
    def adapt(self, feedback):
        w = {}
        if isinstance(feedback, dict) and isinstance(feedback.get("window"), dict):
            w = feedback["window"]
        space = self.meta["param_space"]
        before = dict(self.p)
        bits = []

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

        changes = {k: round(v, 4) for k, v in self.p.items()
                   if abs(v - before.get(k, v)) > 1e-9}
        ret, br = w.get("ret"), w.get("bench_ret")
        head = f"window {ret:+.1%} vs IXIC {br:+.1%}. " if (_ok(ret) and _ok(br)) else ""
        note = head + ("; ".join(bits) if bits else "no usable gradient, parameters held")
        return {"changes": changes, "note": note[:300]}


STRATEGY = Factor()
