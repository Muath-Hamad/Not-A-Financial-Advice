"""trend — trend & cross-sectional momentum desk on the AAOIFI-screened NASDAQ.

Thesis
------
NASDAQ pays for two things and punishes everything else: (1) owning the names
that are already winning, and (2) still being long when the secular uptrend
resumes. The failure mode is not picking the wrong winner, it is (a) sitting in
cash through an advance because a binary regime switch flipped off, and (b)
carrying a broken name through a violent correction. So the whole design is
built around a *continuous* exposure dial and an *asymmetric* exit stack: wide
leashes on winners, short ones on losers, and never a single boolean that can
turn the book off at exactly the wrong moment.

THE RULEBOOK
------------
1. RANKING UNIVERSE (re-derived every session, never a fixed list)
   Price >= $5, trailing turnover EMA >= $8M/day, valid 3m and 6m returns.
   The floor kills the illiquid tail; there is deliberately NO ceiling — on
   this exchange the mega-caps *are* the trend, not an index proxy.

2. CROSS-SECTIONAL SCORE (one number, every name, every day)
   - volatility-adjusted multi-horizon momentum: a weighted blend of 3m/6m/12m
     total return divided by the name's own annualised vol. Risk-adjusted
     momentum survives regime change far better than raw momentum.
   - relative strength versus the composite (rs_bench_3m).
   - proximity to the 52-week high: trend quality, not just trend size.
   - a small bonus for a clean moving-average stack (50 > 100 > 200).
   The 1-month horizon is deliberately excluded (short-term reversal noise).

3. ENTRY GATES (structural, all must hold)
   Above sma50 AND sma200, 12m (or 6m fallback) return positive, within 30% of
   the 52-week high, ATR% in [0.8%, 12%], today's dollar turnover >= $3M, and
   the name must rank inside the top ENTRY_POOL of the cross-section.

4. EXPOSURE — CONTINUOUS, NEVER BINARY. Target gross =
      EXP_MAX x regime x vol_scalar x own_drawdown_scalar
   regime      = 0.40 x ramp(index vs sma200) + 0.30 x ramp(index vs sma50)
                 + 0.30 x ramp(market breadth).  Three soft ramps, so the dial
                 slides between 0 and 1 instead of tripping.
   vol_scalar  = TARGET_VOL / index 21d realised vol, clamped [0.5, 1.15]:
                 the book shrinks automatically as the tape gets violent.
   dd_scalar   = slides 1.0 -> 0.55 as the equity curve falls 10% -> 25% off
                 its high, and slides back up on its own as equity recovers.
                 The high-water reference itself bleeds ~0.15%/session, so a
                 stale peak can never keep the book small through an entire
                 recovery. No sticky "stand down" mode that misses the turn.
   Trimming only happens when the book is more than TRIM_BAND above target, and
   it sells the *weakest-ranked* holdings first, partially. Winners are last.

5. SIZING by volatility, not conviction: weight = RISK_PER_TRADE /
   (STOP_ATR x ATR%), clamped to [0.5x, 2x] of an equal weight; at most
   TARGET_N = 15 names, so no single pick can decide the season; a line that
   compounds past 25% of the book is trimmed back to 20%.

6. EXITS (checked every session, asymmetric by construction)
   - hard stop at HARD_STOP off average cost (gap protection);
   - initial stop at entry - STOP_ATR x ATR(at entry);
   - trailing stop at peak - TRAIL_ATR x ATR, armed once the trade is up
     TRAIL_ARM. Wide on purpose: this is the compounder-protection rule;
   - structural trend break: close below sma200;
   - momentum decay: rank falls outside TARGET_N x RANK_BUFFER;
   - time stop: TIME_STOP sessions without progress is dead money.

7. RE-DEPLOYMENT: when the dial re-opens after a correction, cash goes back to
   work through new entries, or — if all slots are full but the book has shrunk
   well below target — one top-up per session into a healthy top-ranked name.

8. BACK-PROPAGATION (adapt(), every 63 sessions, bounded and deterministic)
   Aggression (EXP_MAX, RISK_PER_TRADE) tracks a smoothed realised Sharpe and
   is pushed *up* when the window under-participated in a rising benchmark and
   *down* after a deep window drawdown. Stops widen when the hit rate says the
   book is being shaken out and tighten when it is comfortably high. The trail
   widens when the win/loss payoff ratio is too thin. The time stop shortens
   when losers are being held longer than winners. The rank buffer widens when
   turnover runs hot. And the momentum horizon weights are nudged toward
   whichever horizon actually paid, using the per-entry attribution recorded at
   trade time. Every step is small, clamped to meta["param_space"], and
   reported for audit.

No dates, no per-ticker plans, no memorised tape. Deterministic, stdlib only,
no IO.
"""

from __future__ import annotations

from strategy_base import Strategy

BENCH = "IXIC"

# --- ranking universe ------------------------------------------------------
PX_MIN = 5.0
LIQ_MIN = 8_000_000.0        # trailing dollar-turnover EMA floor
TURN_TODAY_MIN = 3_000_000.0
TURN_ALPHA = 0.05            # EMA weight on today's turnover

# --- entry gates -----------------------------------------------------------
ATR_LO, ATR_HI = 0.008, 0.120
D52_MIN = -0.30              # must be within 30% of the 52-week high

# --- book ------------------------------------------------------------------
TARGET_N = 15
ENTRY_POOL = 20              # a new name must rank inside this slice of the tape
W_MIN, W_MAX = 0.5 / TARGET_N, 2.0 / TARGET_N
NAME_CAP, NAME_TRIM_TO = 0.25, 0.20
MIN_BUY = 2_500.0
ENTRIES_PER_DAY = 4
REENTRY_COOL = 5
ORDER_GUARD = 3
TRIM_BAND = 0.10             # only de-risk when this far above target gross
RELOAD_GAP = 0.12            # top-up threshold when all slots are full

# --- exits -----------------------------------------------------------------
HARD_STOP = -0.20
TRAIL_ARM = 0.10
TIME_MIN = 0.0

# --- regime ramps (continuous, no switches) --------------------------------
R200_LO, R200_HI = -0.05, 0.02
R50_LO, R50_HI = -0.04, 0.01
BR_LO, BR_HI = 0.32, 0.55
DD_SOFT, DD_HARD, DD_FLOOR = -0.10, -0.25, 0.55
PEAK_DECAY = 0.0015          # the high-water reference bleeds toward equity (~30%/yr)
CRASH_DAY = -0.030
CRASH_COOL = 3
VOL_FLOOR = 0.06
VOL_SCALAR_LO, VOL_SCALAR_HI = 0.50, 1.15

# --- adaptable defaults (deliberately round; adapt() carries the tuning) ----
D_EXP_MAX = 0.95
D_RISK_PER_TRADE = 0.016
D_STOP_ATR = 3.0
D_TRAIL_ATR = 5.0
D_TIME_STOP = 35.0
D_RANK_BUFFER = 2.0
D_TARGET_VOL = 0.17
D_W3, D_W6, D_W12 = 0.30, 0.35, 0.35

MOODS = ("risk on", "trending", "scaling in", "neutral", "de-risking", "defensive")


def _ok(x):
    return isinstance(x, (int, float)) and x == x and -1e18 < x < 1e18


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _ramp(x, lo, hi, default=0.5):
    if not _ok(x) or hi <= lo:
        return default
    return _clamp((x - lo) / (hi - lo), 0.0, 1.0)


class Trend(Strategy):
    meta = {
        "handle": "trend",
        "name": "Trend",
        "style": ("cross-sectional momentum on liquid NASDAQ trends, exposure scaled "
                  "continuously by index trend, breadth and volatility, ATR trailing exits"),
        "risk_style": "trend-following momentum, continuously scaled",
        "color": "#888888",
        "param_space": {
            "EXP_MAX": [0.55, 1.00],
            "RISK_PER_TRADE": [0.008, 0.030],
            "STOP_ATR": [2.0, 4.5],
            "TRAIL_ATR": [3.0, 8.0],
            "TIME_STOP": [20.0, 60.0],
            "RANK_BUFFER": [1.3, 3.0],
            "TARGET_VOL": [0.10, 0.30],
            "W3": [0.12, 0.60],
            "W6": [0.12, 0.60],
            "W12": [0.12, 0.60],
        },
    }

    def __init__(self):
        # adaptable parameters
        self.EXP_MAX = D_EXP_MAX
        self.RISK_PER_TRADE = D_RISK_PER_TRADE
        self.STOP_ATR = D_STOP_ATR
        self.TRAIL_ATR = D_TRAIL_ATR
        self.TIME_STOP = D_TIME_STOP
        self.RANK_BUFFER = D_RANK_BUFFER
        self.TARGET_VOL = D_TARGET_VOL
        self.W3, self.W6, self.W12 = D_W3, D_W6, D_W12
        # state
        self._turn = {}          # code -> EMA of dollar turnover
        self._peak = {}          # code -> peak AdjClose since entry
        self._entry_px = {}      # code -> AdjClose at entry decision
        self._atr0 = {}          # code -> ATR at entry
        self._entry_day = {}     # code -> sim day the fill is expected
        self._cool = {}          # code -> day until which re-entry is barred
        self._ordered = {}       # code -> day a buy was queued (dupe guard)
        self._sell_day = {}      # code -> day a sell was queued (dupe guard)
        self._attr = {}          # code -> (s3, s6, s12) momentum attribution at entry
        self._closed_attr = {}   # code -> attribution of the most recent exit
        self._eq_peak = 0.0
        self._no_buy_until = -1
        self._last_note_day = -99
        self._last_target = None
        self._sh_ema = None
        self._n_adapt = 0

    # ------------------------------------------------------------- scoring
    def _score(self, r):
        """Volatility-adjusted multi-horizon momentum + RS + trend quality.

        Returns (score, (s3, s6, s12)) or None when the row cannot be ranked.
        """
        r3 = r.get("ret_3m")
        r6 = r.get("ret_6m")
        if not _ok(r3) or not _ok(r6):
            return None
        r12 = r.get("ret_12m")
        if not _ok(r12):
            r12 = r6                      # young listing: fall back, never guess
        c3 = self.W3 * _clamp(r3, -0.6, 1.2)
        c6 = self.W6 * _clamp(r6, -0.6, 2.0)
        c12 = self.W12 * _clamp(r12, -0.6, 3.0)
        mom = c3 + c6 + c12
        tot = abs(c3) + abs(c6) + abs(c12)
        if tot > 1e-9:
            attr = (c3 / tot, c6 / tot, c12 / tot)
        else:
            attr = (0.0, 0.0, 0.0)
        v = r.get("vol_21")
        v = _clamp(v, 0.18, 1.50) if _ok(v) else 0.35
        sc = mom / v

        rs = r.get("rs_bench_3m")
        if _ok(rs):
            sc += 0.35 * _clamp(rs, -0.5, 1.0)
        d52 = r.get("dist_52w_high")
        if _ok(d52):
            sc += 0.30 * _clamp(1.0 + d52 * 2.0, 0.0, 1.0)
        s50, s100, s200 = r.get("sma50"), r.get("sma100"), r.get("sma200")
        if _ok(s50) and _ok(s100) and _ok(s200) and s50 > s100 > s200:
            sc += 0.15
        return sc, attr

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0) or 0)
        pos = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        eq = float(portfolio.get("equity", 0.0) or 0.0)
        if not _ok(eq) or eq <= 0:
            eq = 1.0
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = breadth if _ok(breadth) else 0.5
        bret1d = ctx.get("tasi_ret_1d", 0.0)
        bret1d = bret1d if _ok(bret1d) else 0.0

        # high-water reference with a slow bleed: a stale peak must never keep
        # the book small through an entire recovery (the 2018->2019 trap).
        self._eq_peak = max(eq, self._eq_peak * (1.0 - PEAK_DECAY))
        own_dd = (eq / self._eq_peak - 1.0) if self._eq_peak > 0 else 0.0

        # --- causal liquidity state -------------------------------------
        for c, r in view.items():
            if c == BENCH:
                continue
            t = r.get("turnover_sar")
            if _ok(t) and t >= 0.0:
                prev = self._turn.get(c)
                self._turn[c] = t if prev is None else prev + TURN_ALPHA * (t - prev)

        # --- continuous regime dial -------------------------------------
        b = view.get(BENCH) or {}
        bc = b.get("AdjClose")
        g200 = g50 = 0.5
        if _ok(bc) and bc > 0:
            s200 = b.get("sma200")
            if _ok(s200) and s200 > 0:
                g200 = _ramp(bc / s200 - 1.0, R200_LO, R200_HI)
            s50 = b.get("sma50")
            if _ok(s50) and s50 > 0:
                g50 = _ramp(bc / s50 - 1.0, R50_LO, R50_HI)
        gbr = _ramp(breadth, BR_LO, BR_HI)
        regime = 0.40 * g200 + 0.30 * g50 + 0.30 * gbr

        bvol = b.get("vol_21")
        bvol = bvol if (_ok(bvol) and bvol > 0) else 0.15
        vol_scalar = _clamp(self.TARGET_VOL / max(VOL_FLOOR, bvol),
                            VOL_SCALAR_LO, VOL_SCALAR_HI)

        if own_dd < DD_SOFT:
            span = DD_HARD - DD_SOFT
            frac = _clamp((own_dd - DD_SOFT) / span, 0.0, 1.0) if span != 0 else 0.0
            dd_scalar = _clamp(1.0 - frac * (1.0 - DD_FLOOR), DD_FLOOR, 1.0)
        else:
            dd_scalar = 1.0

        target = _clamp(self.EXP_MAX * regime * vol_scalar * dd_scalar, 0.0, self.EXP_MAX)

        if bret1d <= CRASH_DAY:
            self._no_buy_until = max(self._no_buy_until, day + CRASH_COOL)

        # --- rank the whole cross-section --------------------------------
        rows = []
        for c, r in view.items():
            if c == BENCH:
                continue
            px = r.get("AdjClose")
            if not _ok(px) or px <= 0:
                continue
            raw_px = r.get("Close")
            if not _ok(raw_px) or raw_px < PX_MIN:
                continue
            tt = self._turn.get(c)
            if tt is None or tt < LIQ_MIN:
                continue
            s = self._score(r)
            if s is None:
                continue
            rows.append((s[0], c, r, s[1]))
        rows.sort(key=lambda t: (-t[0], t[1]))
        rank = {t[1]: i for i, t in enumerate(rows)}

        orders, sold, exits = [], set(), []

        # --- exits, every session ---------------------------------------
        rank_cut = max(TARGET_N + 2, int(TARGET_N * self.RANK_BUFFER))
        for c, ph in pos.items():
            r = view.get(c)
            up = ph.get("unrealized_pct", 0.0)
            up = up if _ok(up) else 0.0
            px = r.get("AdjClose") if r is not None else None
            if _ok(px):
                self._peak[c] = max(self._peak.get(c, px), px)
            pk = self._peak.get(c)
            e0 = self._entry_px.get(c)
            a0 = self._atr0.get(c)
            atr = r.get("atr14") if r is not None else None
            held = day - self._entry_day.get(c, day)
            reason = None

            if up <= HARD_STOP:
                reason = f"hard stop {up:+.1%}"
            if reason is None and _ok(px) and _ok(e0) and _ok(a0) and a0 > 0:
                lvl = e0 - self.STOP_ATR * a0
                if px <= lvl:
                    reason = f"initial stop: {px:.2f} through {lvl:.2f} ({self.STOP_ATR:.1f} ATR)"
            if reason is None and _ok(px) and _ok(pk) and _ok(atr) and atr > 0 and _ok(e0) and e0 > 0:
                if pk / e0 - 1.0 >= TRAIL_ARM and px <= pk - self.TRAIL_ATR * atr:
                    reason = (f"trail: {px:.2f} vs peak {pk:.2f} less "
                              f"{self.TRAIL_ATR:.1f} ATR; {up:+.1%}")
            if reason is None and r is not None:
                s200 = r.get("sma200")
                if _ok(px) and _ok(s200) and px < s200:
                    reason = f"trend break: below the 200-day; {up:+.1%}"
            if reason is None:
                rk = rank.get(c)
                if rk is None or rk >= rank_cut:
                    reason = f"momentum decay: out of the top {rank_cut}; {up:+.1%}"
            if reason is None and held >= self.TIME_STOP and up < TIME_MIN:
                reason = f"time stop: {held} sessions at {up:+.1%}"

            if reason:
                sold.add(c)
                if 0 <= day - self._sell_day.get(c, -999) <= ORDER_GUARD:
                    continue          # a sell is already queued (halted name)
                self._sell_day[c] = day
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                self._cool[c] = day + REENTRY_COOL
                self._closed_attr[c] = self._attr.get(c)
                exits.append((c, up, reason))
                continue

            w = ph.get("weight", 0.0)
            if _ok(w) and w > NAME_CAP:
                frac = _clamp(1.0 - NAME_TRIM_TO / w, 0.0, 0.6)
                if frac > 0.05:
                    orders.append({"code": c, "side": "sell", "fraction": round(frac, 3),
                                   "reason": f"single-name cap: {w:.0%} back to {NAME_TRIM_TO:.0%}"})

        for c in list(self._peak):
            if c not in pos:
                self._peak.pop(c, None)
                self._entry_px.pop(c, None)
                self._atr0.pop(c, None)
                self._entry_day.pop(c, None)
                self._attr.pop(c, None)

        # --- exposure management: trim the weakest when well above target -
        keep = [(c, ph) for c, ph in pos.items() if c not in sold]
        gross = sum(float(ph.get("value", 0.0) or 0.0) for _, ph in keep) / eq
        proceeds = sum(float(pos[c].get("value", 0.0) or 0.0) for c in sold)

        if gross > target + TRIM_BAND and keep:
            excess = (gross - target) * eq
            worst = sorted(keep, key=lambda t: -(rank.get(t[0], 10 ** 6)))
            for c, ph in worst[:2]:
                if excess <= 0:
                    break
                val = float(ph.get("value", 0.0) or 0.0)
                if val <= 0:
                    continue
                frac = _clamp(excess / val, 0.0, 1.0)
                if frac >= 0.85:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"de-risk to {target:.0%} target gross"})
                    sold.add(c)
                    self._closed_attr[c] = self._attr.get(c)
                    excess -= val
                    proceeds += val
                elif frac > 0.10:
                    orders.append({"code": c, "side": "sell", "fraction": round(frac, 3),
                                   "reason": f"trim {frac:.0%} to {target:.0%} target gross"})
                    excess -= val * frac
                    proceeds += val * frac
            keep = [(c, ph) for c, ph in pos.items() if c not in sold]
            gross = sum(float(ph.get("value", 0.0) or 0.0) for _, ph in keep) / eq

        # --- entries ------------------------------------------------------
        n_open = len(keep)
        n_pend = len([c for c, d0 in self._ordered.items()
                      if c not in pos and 0 <= day - d0 <= ORDER_GUARD])
        slots = TARGET_N - n_open - n_pend
        avail_cash = cash + 0.9 * proceeds
        room = max(0.0, target - gross) * eq
        budget = max(0.0, min(avail_cash, room))
        can_buy = day > self._no_buy_until and budget >= MIN_BUY

        bought = 0
        if can_buy and slots > 0:
            for sc, c, r, attr in rows[:ENTRY_POOL]:
                if bought >= ENTRIES_PER_DAY or slots <= 0 or budget < MIN_BUY:
                    break
                if c in pos or c in sold:
                    continue
                if day <= self._cool.get(c, -1):
                    continue
                if 0 <= day - self._ordered.get(c, -999) <= ORDER_GUARD:
                    continue
                px = r.get("AdjClose")
                s50, s200 = r.get("sma50"), r.get("sma200")
                if not (_ok(s50) and _ok(s200) and px > s50 and px > s200):
                    continue
                r12 = r.get("ret_12m")
                if not _ok(r12):
                    r12 = r.get("ret_6m")
                if not _ok(r12) or r12 <= 0:
                    continue
                d52 = r.get("dist_52w_high")
                if not _ok(d52) or d52 < D52_MIN:
                    continue
                apct = r.get("atr_pct")
                if not _ok(apct) or apct < ATR_LO or apct > ATR_HI:
                    continue
                t_today = r.get("turnover_sar")
                if not _ok(t_today) or t_today < TURN_TODAY_MIN:
                    continue

                stop_d = max(0.03, self.STOP_ATR * apct)
                w = _clamp(self.RISK_PER_TRADE / stop_d, W_MIN, W_MAX)
                usd = min(w * eq, budget)
                if usd < MIN_BUY:
                    continue
                orders.append({"code": c, "side": "buy", "sar": round(usd, 2),
                               "reason": (f"rank {rank.get(c, 0) + 1} momentum, {abs(d52):.0%} "
                                          f"off the 52w high, ATR {apct:.1%} -> {w:.0%} line")})
                self._ordered[c] = day
                self._entry_day[c] = day + 1
                self._entry_px[c] = px if _ok(px) else 0.0
                self._peak[c] = px if _ok(px) else 0.0
                a = r.get("atr14")
                self._atr0[c] = a if (_ok(a) and a > 0) else None
                self._attr[c] = attr
                budget -= usd
                slots -= 1
                bought += 1

        # --- re-deployment when the book has shrunk but slots are full ----
        if (can_buy and bought == 0 and slots <= 0 and keep
                and gross < target - RELOAD_GAP and budget >= MIN_BUY):
            best = None
            for c, ph in keep:
                rk = rank.get(c)
                if rk is None or rk >= TARGET_N:
                    continue
                r = view.get(c) or {}
                px, s50 = r.get("AdjClose"), r.get("sma50")
                up = ph.get("unrealized_pct", 0.0)
                if not (_ok(px) and _ok(s50) and px > s50):
                    continue
                if not _ok(up) or up < -0.03:
                    continue
                apct = r.get("atr_pct")
                if not _ok(apct) or apct < ATR_LO or apct > ATR_HI:
                    continue
                w = float(ph.get("weight", 0.0) or 0.0)
                tgt_w = _clamp(self.RISK_PER_TRADE / max(0.03, self.STOP_ATR * apct),
                               W_MIN, W_MAX)
                if w >= 0.75 * tgt_w:
                    continue
                if best is None or rk < best[0]:
                    best = (rk, c, (tgt_w - w) * eq)
            if best is not None:
                usd = min(best[2], budget)
                if usd >= MIN_BUY:
                    orders.append({"code": best[1], "side": "buy", "sar": round(usd, 2),
                                   "reason": f"top-up: book {gross:.0%} vs {target:.0%} target"})
                    self._ordered[best[1]] = day
                    budget -= usd

        # --- journal: sparse, only on real events -------------------------
        sent = _clamp(2.0 * regime - 1.0 + 0.5 * (dd_scalar - 1.0), -1.0, 1.0)
        mood = MOODS[min(len(MOODS) - 1, int((1.0 - min(target, 1.0)) * len(MOODS)))]
        note = ""
        big = [e for e in exits if abs(e[1]) >= 0.15]
        if big:
            c, up, reason = max(big, key=lambda e: abs(e[1]))
            nm = (ctx.get("names") or {}).get(c, c)
            note = f"Closed {nm} at {up:+.1%} — {reason}. Book now {gross:.0%} invested."
            self._last_note_day = day
        elif (self._last_target is None or abs(target - self._last_target) >= 0.25) \
                and day - self._last_note_day >= 5:
            note = (f"Exposure dial to {target:.0%} (regime {regime:.2f}, index vol "
                    f"{bvol:.0%}, breadth {breadth:.0%}, own drawdown {own_dd:+.1%}).")
            self._last_target = target
            self._last_note_day = day
        if self._last_target is None:
            self._last_target = target

        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}

    # --------------------------------------------------------------- adapt
    def adapt(self, feedback):
        """Bounded, deterministic gradient-like steps on realised feedback."""
        if not isinstance(feedback, dict):
            return None
        w = feedback.get("window") or {}
        trades = feedback.get("trades") or []
        space = self.meta["param_space"]
        before = {k: getattr(self, k) for k in space}
        self._n_adapt += 1

        def num(x, d=None):
            return x if _ok(x) else d

        sh = num(w.get("sharpe"), 0.0)
        ret = num(w.get("ret"), 0.0)
        bret = num(w.get("bench_ret"), 0.0)
        mdd = num(w.get("max_dd"), 0.0)
        hr = num(w.get("hit_rate"))
        expo = num(w.get("avg_exposure"), 0.5)
        turn = num(w.get("turnover"), 0.0)
        n_sells = num(w.get("n_sells"), 0) or 0

        self._sh_ema = sh if self._sh_ema is None else 0.7 * self._sh_ema + 0.3 * sh
        she = self._sh_ema
        why = []

        # 1) aggression follows smoothed realised Sharpe, participation and pain
        step = 0.0
        if she > 1.00:
            step += 0.03
            why.append("sharpe strong")
        elif she < 0.20:
            step -= 0.03
            why.append("sharpe weak")
        if bret > 0.02 and (ret - bret) < -0.02 and expo < 0.85:
            step += 0.03
            why.append("under-participated a rising tape")
        if mdd < -0.18:
            step -= 0.05
            why.append("deep window drawdown")
        if step:
            self.EXP_MAX = _clamp(self.EXP_MAX + step, *space["EXP_MAX"])

        rstep = _clamp(0.0015 * (she - 0.60), -0.0015, 0.0015)
        if mdd < -0.18:
            rstep -= 0.0020
        self.RISK_PER_TRADE = _clamp(self.RISK_PER_TRADE + rstep, *space["RISK_PER_TRADE"])

        # 2) stop width follows the hit rate (are we being shaken out?)
        if hr is not None and n_sells >= 5:
            if hr < 0.35:
                self.STOP_ATR = _clamp(self.STOP_ATR + 0.15, *space["STOP_ATR"])
                why.append(f"hit rate {hr:.0%} -> wider stop")
            elif hr > 0.55:
                self.STOP_ATR = _clamp(self.STOP_ATR - 0.10, *space["STOP_ATR"])
                why.append(f"hit rate {hr:.0%} -> tighter stop")

        # 3) trail width follows the win/loss payoff ratio
        wins = [t.get("realized_pnl") for t in trades if _ok(t.get("realized_pnl"))
                and t.get("realized_pnl") > 0]
        losses = [-t.get("realized_pnl") for t in trades if _ok(t.get("realized_pnl"))
                  and t.get("realized_pnl") <= 0]
        if len(wins) >= 2 and len(losses) >= 2:
            aw = sum(wins) / len(wins)
            al = sum(losses) / len(losses)
            payoff = aw / al if al > 0 else 99.0
            if payoff < 1.8:
                self.TRAIL_ATR = _clamp(self.TRAIL_ATR + 0.25, *space["TRAIL_ATR"])
                why.append(f"payoff {payoff:.1f} -> wider trail")
            elif payoff > 3.5:
                self.TRAIL_ATR = _clamp(self.TRAIL_ATR - 0.20, *space["TRAIL_ATR"])
                why.append(f"payoff {payoff:.1f} -> tighter trail")

        # 4) time stop follows hold asymmetry (losers must not outlive winners)
        def _held_days(t):
            hs = t.get("held_since")
            d = feedback.get("date")
            if not isinstance(hs, str) or not isinstance(d, str):
                return None
            try:
                y1, m1, d1 = (int(x) for x in hs[:10].split("-"))
                y2, m2, d2 = (int(x) for x in d[:10].split("-"))
            except (ValueError, TypeError):
                return None
            return (y2 * 365 + m2 * 30 + d2) - (y1 * 365 + m1 * 30 + d1)

        hw = [_held_days(t) for t in trades if _ok(t.get("realized_pnl")) and t["realized_pnl"] > 0]
        hl = [_held_days(t) for t in trades if _ok(t.get("realized_pnl")) and t["realized_pnl"] <= 0]
        hw = [x for x in hw if x is not None]
        hl = [x for x in hl if x is not None]
        if len(hw) >= 2 and len(hl) >= 2:
            if sum(hl) / len(hl) > sum(hw) / len(hw):
                self.TIME_STOP = _clamp(self.TIME_STOP - 2.0, *space["TIME_STOP"])
                why.append("losers outliving winners -> shorter time stop")
            else:
                self.TIME_STOP = _clamp(self.TIME_STOP + 1.0, *space["TIME_STOP"])

        # 5) rank buffer follows realised turnover
        if turn > 5.0:
            self.RANK_BUFFER = _clamp(self.RANK_BUFFER + 0.15, *space["RANK_BUFFER"])
            why.append(f"turnover {turn:.1f}x -> wider rank buffer")
        elif turn < 1.5:
            self.RANK_BUFFER = _clamp(self.RANK_BUFFER - 0.10, *space["RANK_BUFFER"])

        # 6) volatility target follows realised pain / reward
        if mdd < -0.20:
            self.TARGET_VOL = _clamp(self.TARGET_VOL - 0.01, *space["TARGET_VOL"])
        elif she > 1.00 and mdd > -0.10:
            self.TARGET_VOL = _clamp(self.TARGET_VOL + 0.01, *space["TARGET_VOL"])

        # 7) momentum horizon weights follow which horizon actually paid
        g = [0.0, 0.0, 0.0]
        seen = 0
        for t in trades:
            a = self._closed_attr.get(t.get("code"))
            p = t.get("realized_pnl")
            if not a or not _ok(p):
                continue
            seen += 1
            for k in range(3):
                g[k] += p * a[k]
        if seen >= 4:
            mag = sum(abs(x) for x in g)
            if mag > 1e-9:
                cur = [self.W3, self.W6, self.W12]
                tgt = [max(0.0, x) / mag for x in g]
                ssum = sum(tgt)
                if ssum > 1e-9:
                    tgt = [x / ssum for x in tgt]
                    new = [_clamp(cur[k] + 0.06 * (tgt[k] - cur[k]), *space["W3"])
                           for k in range(3)]
                    tot = sum(new)
                    if tot > 1e-9:
                        self.W3, self.W6, self.W12 = (x / tot for x in new)
                        why.append("shifted momentum horizons toward what paid")
        self._closed_attr.clear()

        changes = {}
        for k, v0 in before.items():
            v1 = getattr(self, k)
            if abs(v1 - v0) > 1e-9:
                changes[k] = round(v1, 4)
        note = ("; ".join(why) if why else "steady state") + \
               f" | sharpe {sh:.2f} (ema {she:.2f}), ret {ret:+.1%} vs bench {bret:+.1%}, " \
               f"dd {mdd:.1%}, exposure {expo:.0%}"
        return {"changes": changes, "note": note[:300]}


STRATEGY = Trend()
