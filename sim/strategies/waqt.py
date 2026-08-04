"""Waqt — regime & rotation. Timing is the position; the names are just how you express it.

Process, top-down, every session:

1. REGIME MODEL. Four independent readings of the tape, blended into one score in
   [-1, +1]: (a) index trend — TASI against its 20/50/100/200d averages, (b) breadth —
   the share of the market above its own 50d plus the 5v20 slope of that share,
   (c) index momentum — 1m and 3m index returns scaled by their own volatility,
   (d) stress — realized vol against its trailing norm, distance from the 52-week
   high, and a run-of-down-days counter. Stress subtracts; the rest add.

2. EXPOSURE. The score maps to a target gross on a ramp quantised into three decisive
   rungs — fully invested, half, cash — so the book moves in real steps instead of
   drifting a percent at a time, with a small dead-band so noise cannot rattle it.
   Three overrides jump the queue and fire the same session, no confirmation waited for:
     - CIRCUIT BREAKER: an index air-pocket on collapsing breadth cuts gross to a
       fifth immediately.
     - THRUST: breadth vaulting from washed out to expanding inside a few weeks forces
       gross back to full before the slow trend signals agree. Bottoms do not ring a
       bell; participation is the closest thing to one.
     - EQUITY STOP: my own drawdown past 7% from peak halves the book until the regime
       score prints clean again. Position risk is a market opinion; account risk is not.

3. ROTATION. Sectors are ranked on median 3m/6m member momentum; that rank becomes a
   tilt on every name's score, not a gate — leadership sometimes hides in a sector
   whose median is dead, and a gate would never let me own it. Below full exposure the
   tilt swings toward the defensive sleeves. Names are scored on a 1m/3m/6m/12m
   momentum blend, risk-adjusted by realised vol, with credit for trading near the
   52-week high, then filtered on trend (above the 50d and 100d), liquidity (20-day
   traded value, judged relative to the market as well as absolutely) and history
   (no name without a 3m record, which keeps fresh IPOs out until they have one).
   Eight seats at most, two per sector, sized inverse to volatility.

4. HOLDING. An incumbent keeps its seat while its own trend is intact — re-ranking a
   live winner out of the book every fortnight is how you pay commission for the
   privilege of missing the trend. Selling is done by rules that describe the position,
   not the calendar: an ATR-scaled trailing stop from the post-entry high, a break of
   the 50d, a hard stop from cost, and the regime itself. A stopped-out name is benched
   so I cannot re-buy my own mistake.

5. PEERS, if any exist, are a fifth regime input and nothing more: how deployed the
   best-performing half of the field is nudges my score by a few points, and names the
   two leaders own get a small scoring credit. Standalone the rulebook is unchanged.
"""

from __future__ import annotations

import math

from strategy_base import Strategy

P = {
    # --- regime blend weights ---
    "w_trend": 0.34,
    "w_breadth": 0.30,
    "w_mom": 0.10,
    "w_stress": 0.17,
    "t_gap_div": 0.03,       # index-to-average gap that counts as a full trend vote
    "b_div": 0.14,           # breadth spread around 50% that counts as a full vote
    "b_slope_div": 0.09,     # 5v20 breadth slope that counts as a full vote
    "mom_div1": 0.035,       # 1m index move that counts as a full vote
    "mom_div3": 0.070,       # 3m index move that counts as a full vote
    "dd_div": 0.13,          # distance below the 52w high that counts as full stress
    "vol_div": 0.50,         # excess over the trailing vol norm that counts as full stress
    # --- exposure ramp: score -> gross ---
    "ramp_lo": -0.26,        # score at which gross hits 0
    "ramp_hi": 0.20,         # score at which gross hits 1
    "gross_step": 0.50,      # quantisation of the target
    "up_band": 0.06,         # must beat current gross by this to add
    "down_band": 0.06,       # ...but only this to cut (asymmetric on purpose)
    # --- overrides ---
    "panic_ret": -0.018,     # index air-pocket
    "panic_breadth": 0.46,
    "panic_gross": 0.20,
    "thrust_lo": 0.34,       # breadth washout level
    "thrust_hi": 0.55,       # breadth expansion level
    "thrust_win": 18,        # sessions allowed between the two
    "thrust_gross": 1.00,
    "eq_stop_dd": -0.07,     # own drawdown that halves the book
    "eq_stop_gross": 0.50,
    "eq_stop_clear": 0.20,   # regime score needed to re-arm
    # --- book construction ---
    "rebal_every": 10,
    "max_names_on": 8,
    "max_w": 0.20,
    "max_per_sector": 2,
    "trim_band": 0.06,       # let a winner run this far past its target before trimming
    "def_tilt": 0.25,         # ...or merely tilt it toward them
    "min_order": 3000.0,
    "hold_buffer": 50,        # held name survives while inside top N+buffer
    "min_liq": 3.0e6,        # SAR of 20-day average traded value
    "liq_rel": 0.60,         # ...or this multiple of the market's median, whichever is kinder
    "liq_mult": 25.0,        # position must be <= 1/25 of daily traded value
    # --- name scoring ---
    "s_m1": 0.10,
    "s_m3": 0.25,
    "s_m6": 0.35,
    "s_m12": 0.30,
    "vol_pow": 0.5,
    "vol_floor": 0.16,
    "hi_bonus": 0.30,        # credit for trading near the 52w high
    "sec_tilt": 0.18,        # weight of the sector rank tilt
    "rsi_max": 88.0,
    # --- exits ---
    "trail_k": 4.0,          # x daily ATR%
    "trail_min": 0.09,
    "trail_max": 0.24,
    "hard_stop": -0.11,
    "break_days": 6,         # grace period before the trend-break rule applies
    "bench_days": 25,        # re-entry ban after a stop
    # --- peers ---
    "peer_gross": 0.06,
    "peer_name": 0.10,
}

DEFENSIVE = ("Healthcare", "Food & Staples", "Telecom & IT", "Utilities")


def ok(x) -> bool:
    return isinstance(x, (int, float)) and x == x and not math.isinf(x)


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def g(row, key):
    v = row.get(key)
    return v if ok(v) else None


class Waqt(Strategy):
    meta = {
        "handle": "waqt",
        "name": "Waqt",
        "emoji": "⏳",
        "tagline": "The regime decides the size. The tape decides the names.",
        "risk_style": "regime-timed sector rotation",
        "character": (
            "A top-down allocator who believes exposure is the only decision that "
            "compounds: he reads trend, breadth, volatility and drawdown as one "
            "instrument and moves the whole book on it, early and without asking "
            "the tape for permission twice. Inside a risk-on regime he owns "
            "leadership and nothing else; inside a risk-off one he owns cash and "
            "says so plainly."
        ),
        "color": "#888888",
    }

    def __init__(self):
        self.p = dict(P)
        self.breadth_hist = []
        self.vol_hist = []
        self.gross = 0.0
        self.regime = "cold-start"
        self.last_rebal = -99
        self.peak = {}          # code -> highest close seen while held
        self.opened = {}        # code -> day index of first order
        self.bench = {}         # code -> day index until which entry is banned
        self.eq_peak = 0.0
        self.eq_locked = False
        self.thrust_low_day = -99
        self.down_run = 0
        self.prev_regime = "cold-start"
        self.note_idx = 0

    # ------------------------------------------------------------------ regime
    def _regime(self, view, ctx):
        p = self.p
        t = view.get("TASI") or {}
        c = g(t, "Close")

        trend = 0.0
        tw = 0.0
        for key, w in (("sma20", 0.20), ("sma50", 0.30), ("sma100", 0.20), ("sma200", 0.30)):
            s = g(t, key)
            if c is not None and s is not None and s > 0:
                gap = clamp((c / s - 1.0) / p["t_gap_div"], -1.0, 1.0)
                trend += w * gap
                tw += w
        trend = trend / tw if tw > 0 else 0.0

        b = ctx.get("breadth_sma50", 0.5)
        b = b if ok(b) else 0.5
        self.breadth_hist.append(b)
        if len(self.breadth_hist) > 60:
            self.breadth_hist.pop(0)
        h = self.breadth_hist
        b5 = sum(h[-5:]) / len(h[-5:])
        b20 = sum(h[-20:]) / len(h[-20:])
        b_lvl = clamp((b - 0.50) / p["b_div"], -1.0, 1.0)
        b_slope = clamp((b5 - b20) / p["b_slope_div"], -1.0, 1.0)
        breadth = 0.65 * b_lvl + 0.35 * b_slope

        m1, m3 = g(t, "ret_1m"), g(t, "ret_3m")
        mom = 0.0
        mw = 0.0
        if m1 is not None:
            mom += 0.5 * clamp(m1 / p["mom_div1"], -1.0, 1.0)
            mw += 0.5
        if m3 is not None:
            mom += 0.5 * clamp(m3 / p["mom_div3"], -1.0, 1.0)
            mw += 0.5
        mom = mom / mw if mw > 0 else 0.0

        v = g(t, "vol_21")
        if v is not None:
            self.vol_hist.append(v)
            if len(self.vol_hist) > 250:
                self.vol_hist.pop(0)
        vs = sorted(self.vol_hist)
        vmed = vs[len(vs) // 2] if vs else None
        v_stress = (clamp((v / vmed - 1.0) / p["vol_div"], 0.0, 1.0)
                    if (v and vmed and vmed > 0) else 0.0)
        dh = g(t, "dist_52w_high")
        dd_stress = clamp(-(dh or 0.0) / p["dd_div"], 0.0, 1.0)
        tret = ctx.get("tasi_ret_1d", 0.0)
        tret = tret if ok(tret) else 0.0
        self.down_run = self.down_run + 1 if tret < 0 else 0
        run_stress = clamp((self.down_run - 2) / 4.0, 0.0, 1.0)
        stress = 0.45 * dd_stress + 0.35 * v_stress + 0.20 * run_stress

        score = (p["w_trend"] * trend + p["w_breadth"] * breadth
                 + p["w_mom"] * mom - p["w_stress"] * stress)
        return score, {"trend": trend, "breadth": breadth, "mom": mom, "stress": stress,
                       "b": b, "b5": b5, "b20": b20, "tret": tret,
                       "dist_hi": dh if dh is not None else 0.0}

    def _target_gross(self, score, d, ctx, portfolio, peers):
        p = self.p
        day = ctx["day_index"]

        # Peers are a fifth regime input, not a boss: how deployed are the books with
        # the best 3-month record? Capped hard, and added to the score so the exposure
        # ladder stays in whole steps.
        peer_adj = 0.0
        if peers:
            ranked = sorted(peers.values(), key=lambda q: q.get("ret_63") or 0.0, reverse=True)
            top = ranked[:max(1, len(ranked) // 2)]
            dep = [1.0 - clamp(q.get("cash_frac") or 0.0, 0.0, 1.0) for q in top]
            if dep:
                peer_adj = p["peer_gross"] * clamp((sum(dep) / len(dep) - 0.5) * 2.0, -1.0, 1.0)

        raw = clamp((score + peer_adj - p["ramp_lo"]) / max(1e-6, p["ramp_hi"] - p["ramp_lo"]),
                    0.0, 1.0)
        tgt = round(raw / p["gross_step"]) * p["gross_step"]
        why = "ramp"

        # --- thrust: breadth vaulting out of a washout ---
        if d["b"] <= p["thrust_lo"]:
            self.thrust_low_day = day
        thrust = (d["b"] >= p["thrust_hi"] and d["b5"] > d["b20"]
                  and 0 < day - self.thrust_low_day <= p["thrust_win"])
        if thrust:
            tgt = max(tgt, p["thrust_gross"])
            why = "thrust"

        # --- circuit breaker: air-pocket on bad breadth ---
        panic = d["tret"] <= p["panic_ret"] and d["b"] < p["panic_breadth"]
        if panic:
            tgt = min(tgt, p["panic_gross"])
            why = "breaker"

        # --- own-equity stop ---
        eq = portfolio.get("equity", 0.0) or 0.0
        self.eq_peak = max(self.eq_peak, eq)
        dd = (eq / self.eq_peak - 1.0) if self.eq_peak > 0 else 0.0
        if dd <= p["eq_stop_dd"]:
            self.eq_locked = True
        elif self.eq_locked and score >= p["eq_stop_clear"]:
            self.eq_locked = False
        if self.eq_locked and not thrust:
            tgt = min(tgt, p["eq_stop_gross"])
            why = "equity stop"

        # --- hysteresis: slow to add, quick to cut ---
        if tgt > self.gross + p["up_band"]:
            new = tgt
        elif tgt < self.gross - p["down_band"]:
            new = tgt
        elif why in ("breaker", "thrust", "equity stop") and abs(tgt - self.gross) > 0.02:
            new = tgt
        else:
            new = self.gross
        return clamp(new, 0.0, 1.0), why, dd, thrust, panic

    # -------------------------------------------------------------- selection
    def _sector_scores(self, view, ctx):
        sectors = ctx.get("sectors") or {}
        buckets = {}
        for c, r in view.items():
            if c == "TASI":
                continue
            m3, m6 = g(r, "ret_3m"), g(r, "ret_6m")
            if m3 is None:
                continue
            buckets.setdefault(sectors.get(c, "Other"), []).append(
                0.6 * m3 + 0.4 * (m6 if m6 is not None else m3))
        out = {}
        for s, vals in buckets.items():
            if len(vals) < 3:
                continue
            vals.sort()
            out[s] = vals[len(vals) // 2]
        if not out:
            return {}, {}
        lo, hi = min(out.values()), max(out.values())
        rng = max(1e-6, hi - lo)
        return out, {s: (v - lo) / rng * 2.0 - 1.0 for s, v in out.items()}

    def _candidates(self, view, ctx, positions, equity, peer_hold, weak=False):
        p = self.p
        sectors = ctx.get("sectors") or {}
        _raw, sec_z = self._sector_scores(view, ctx)
        day = ctx["day_index"]

        # Liquidity is judged relative to the market as well as in absolute SAR: feeds
        # go through stretches where reported volume is a fraction of reality, and an
        # absolute floor would bench the whole universe exactly when I want to be long.
        liqs = []
        for c, r in view.items():
            if c == "TASI":
                continue
            v, px = g(r, "vol_sma20"), g(r, "Close")
            if v is not None and px is not None and px > 0 and v > 0:
                liqs.append(v * px)
        liqs.sort()
        med_liq = liqs[len(liqs) // 2] if liqs else 0.0
        liq_floor = min(p["min_liq"], p["liq_rel"] * med_liq) if med_liq > 0 else 0.0
        data_sane = med_liq >= p["min_liq"] * 0.35

        out = []
        for c, r in view.items():
            if c == "TASI":
                continue
            px = g(r, "Close")
            m3 = g(r, "ret_3m")
            if px is None or px <= 0 or m3 is None:
                continue                      # no 3m record -> not investable yet
            m1, m6, m12 = g(r, "ret_1m"), g(r, "ret_6m"), g(r, "ret_12m")
            num = p["s_m3"] * m3
            den = p["s_m3"]
            if m1 is not None:
                num += p["s_m1"] * m1
                den += p["s_m1"]
            if m6 is not None:
                num += p["s_m6"] * m6
                den += p["s_m6"]
            if m12 is not None:
                num += p["s_m12"] * m12
                den += p["s_m12"]
            blend = num / den
            vol = g(r, "vol_21")
            vol = max(p["vol_floor"], vol if vol is not None else 0.30)
            score = blend / (vol ** p["vol_pow"])
            dh = g(r, "dist_52w_high")
            if dh is not None:
                score += p["hi_bonus"] * clamp(1.0 + dh / 0.15, -1.0, 1.0)
            score += p["sec_tilt"] * sec_z.get(sectors.get(c, "Other"), 0.0)
            if weak:
                score += p["def_tilt"] * (0.5 if sectors.get(c) in DEFENSIVE else -0.5)
            if c in peer_hold:
                score += p["peer_name"] * peer_hold[c]

            held = c in positions
            liq = g(r, "vol_sma20")
            liq = liq * px if liq is not None else (g(r, "turnover_sar") or 0.0)
            s50, s100 = g(r, "sma50"), g(r, "sma100")
            rsi = g(r, "rsi14")
            entry_ok = (liq >= liq_floor
                        and (s50 is None or px > s50)
                        and (s100 is None or px > s100)
                        and m3 > 0.0
                        and (rsi is None or rsi <= p["rsi_max"])
                        and day >= self.bench.get(c, -99))
            out.append({"code": c, "score": score, "entry_ok": bool(entry_ok),
                        "held": held, "liq": liq if data_sane else float("inf"),
                        "sec": sectors.get(c, "Other"),
                        "px": px, "m3": m3, "m1": m1 if m1 is not None else 0.0})
        out.sort(key=lambda x: (-x["score"], x["code"]))
        return out, _raw, sec_z

    # ------------------------------------------------------------------ decide
    def decide(self, date, view, portfolio, ctx):
        p = self.p
        day = ctx["day_index"]
        names = ctx.get("names") or {}
        positions = portfolio.get("positions") or {}
        cash = portfolio.get("cash", 0.0) or 0.0
        equity = max(portfolio.get("equity", 0.0) or 0.0, 1.0)
        peers = ctx.get("peers") or {}

        score, d = self._regime(view, ctx)

        # peer holdings of the leaders (confirmation only)
        peer_hold = {}
        if peers:
            ranked = sorted(peers.items(), key=lambda kv: kv[1].get("ret_63") or 0.0,
                            reverse=True)
            for _h, q in ranked[:2]:
                for c, w in (q.get("positions") or {}).items():
                    peer_hold[c] = min(1.0, peer_hold.get(c, 0.0) + max(0.0, w) * 4.0)

        gross, why, own_dd, thrust, panic = self._target_gross(score, d, ctx, portfolio, peers)
        prev_gross = self.gross
        self.gross = gross
        regime = ("risk-on" if gross >= 0.75 else "constructive" if gross >= 0.45
                  else "defensive" if gross >= 0.20 else "risk-off")
        flipped = regime != self.regime
        if flipped:
            self.prev_regime, self.regime = self.regime, regime

        orders, sells, buys, evt = [], [], [], []
        sold = set()

        # -------------------------------------------------- daily name-level exits
        for c, pos in positions.items():
            r = view.get(c)
            if r is None:
                continue
            px = g(r, "Close")
            if px is None or px <= 0:
                continue
            self.peak[c] = max(self.peak.get(c, px), px)
            upnl = pos.get("unrealized_pct", 0.0) or 0.0
            atrp = g(r, "atr_pct")
            trail = clamp(p["trail_k"] * (atrp if atrp is not None else 0.02),
                          p["trail_min"], p["trail_max"])
            held_days = day - self.opened.get(c, day)
            s50 = g(r, "sma50")
            reason = None
            if upnl <= p["hard_stop"]:
                reason = f"hard stop {upnl:+.1%} from cost"
            elif px <= self.peak[c] * (1.0 - trail):
                reason = (f"trailing stop: {px / self.peak[c] - 1:.1%} off the "
                          f"{self.peak[c]:.2f} high, band {trail:.0%}")
            elif (held_days >= p["break_days"] and s50 is not None and px < s50
                  and (g(r, "ret_1m") or 0.0) < 0.0):
                reason = f"trend break: below the 50d ({px:.2f} vs {s50:.2f})"
            if reason:
                sells.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sold.add(c)
                self.bench[c] = day + p["bench_days"]
                evt.append(("stop", c, upnl, reason))

        rebal = (day - self.last_rebal >= p["rebal_every"]) or flipped or thrust or panic
        cands, sec_raw, sec_z = self._candidates(view, ctx, positions, equity, peer_hold,
                                                 weak=gross < 0.75)
        rank = {x["code"]: i for i, x in enumerate(cands)}

        n_target = p["max_names_on"]
        if gross < 0.75:
            n_target = max(2, int(round(p["max_names_on"] * clamp(gross / 0.90, 0.3, 1.0))))
        if gross <= 0.02:
            n_target = 0

        want = []
        if rebal and n_target > 0:
            per_sec = {}
            chosen = set()

            def take(x):
                want.append(x)
                chosen.add(x["code"])
                per_sec[x["sec"]] = per_sec.get(x["sec"], 0) + 1

            # 1) incumbents first: a name I already own keeps its seat while it stays
            #    inside the top N+buffer and still trades above its own 50d. Re-ranking
            #    a live winner out of the book every fortnight is how you pay commission
            #    for the privilege of missing the trend.
            for x in cands:
                if len(want) >= n_target:
                    break
                c = x["code"]
                if c in sold or not x["held"] or rank[c] >= n_target + p["hold_buffer"]:
                    continue
                r = view.get(c) or {}
                s50 = g(r, "sma50")
                if s50 is not None and x["px"] < s50:
                    continue
                if x["m3"] <= 0.0:
                    continue
                take(x)
            # 2) fill the remaining seats with fresh leadership
            for x in cands:
                if len(want) >= n_target:
                    break
                c = x["code"]
                if c in sold or c in chosen or not x["entry_ok"]:
                    continue
                if per_sec.get(x["sec"], 0) >= p["max_per_sector"]:
                    continue
                take(x)

        # ------------------------------------------------------ exits by rotation
        if rebal:
            self.last_rebal = day
            keep = {x["code"] for x in want}
            for c, pos in positions.items():
                if c in sold or c in keep:
                    continue
                if view.get(c) is None:
                    continue
                upnl = pos.get("unrealized_pct", 0.0) or 0.0
                if n_target == 0:
                    why_s = f"regime {regime} (score {score:+.2f}) — to cash"
                else:
                    why_s = (f"rotation: out of the top {n_target}, rank "
                             f"{rank.get(c, 999) + 1}")
                sells.append({"code": c, "side": "sell", "all": True, "reason": why_s})
                sold.add(c)
                evt.append(("rot_out", c, upnl, why_s))

        # ---------------------------------------------------- exposure management
        held_val = sum(pos["value"] for c, pos in positions.items() if c not in sold)
        proceeds = sum(positions[c]["value"] for c in sold if c in positions)
        budget = cash + proceeds * 0.9975
        inv_after = held_val / equity

        if want:
            w_each = min(p["max_w"], gross / max(1, len(want)))
            # inverse-volatility sizing: the quiet compounder carries more of the book
            # than the lottery ticket sitting next to it in the ranking.
            inv_vol = {}
            for x in want:
                v = g(view.get(x["code"]) or {}, "vol_21")
                inv_vol[x["code"]] = 1.0 / max(p["vol_floor"], v if v is not None else 0.30)
            tot = sum(inv_vol.values()) or 1.0
            for c2 in inv_vol:
                inv_vol[c2] = min(p["max_w"], gross * inv_vol[c2] / tot)
            # trim anything running hot above the cap
            for x in want:
                c = x["code"]
                w_c = inv_vol.get(c, w_each)
                pos = positions.get(c)
                if pos and pos["weight"] > w_c + p["trim_band"]:
                    frac = (pos["weight"] - w_c) / pos["weight"]
                    sells.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                  "reason": f"trim {pos['weight']:.0%} back to {w_c:.0%}"})
                    budget += frac * pos["value"] * 0.9975
                    held_val -= frac * pos["value"]
            room = max(0.0, gross * equity - held_val)
            budget = min(budget, room + 1.0)
            for x in want:
                c = x["code"]
                cur = positions.get(c, {}).get("value", 0.0) if c not in sold else 0.0
                w_c = inv_vol.get(c, w_each)
                gap = w_c * equity - cur
                if gap < p["min_order"] or budget < p["min_order"]:
                    continue
                if not x["entry_ok"] and cur <= 0.0:
                    continue
                amt = min(gap, budget, x["liq"] / p["liq_mult"])
                if amt < p["min_order"]:
                    continue
                buys.append({"code": c, "side": "buy", "sar": round(amt, 2),
                             "reason": (f"{x['sec']} tilt {sec_z.get(x['sec'], 0.0):+.2f}, "
                                        f"3m {x['m3']:+.1%}, score {x['score']:+.2f}, "
                                        f"target {w_c:.0%} in a {regime} tape")})
                budget -= amt * 1.002
                if c not in positions:
                    self.opened[c] = day + 1
                    self.peak.pop(c, None)
                evt.append(("buy", c, x["m3"], x["score"]))
        elif inv_after > gross + 0.08 and not sold:
            # over-exposed with nothing worth keeping: shed the weakest name
            live = [(rank.get(c, 999), c) for c in positions if c not in sold]
            if live:
                live.sort(reverse=True)
                c = live[0][1]
                sells.append({"code": c, "side": "sell", "all": True,
                              "reason": f"cutting gross to {gross:.0%}: weakest name in the book"})
                sold.add(c)
                evt.append(("derisk", c, positions[c].get("unrealized_pct", 0.0), ""))

        # gross cut with names still wanted: sell from the bottom of the book
        if not rebal and inv_after > gross + 0.10:
            live = sorted(((rank.get(c, 999), c) for c in positions if c not in sold),
                          reverse=True)
            excess = (inv_after - gross) * equity
            for _rk, c in live:
                if excess <= p["min_order"]:
                    break
                v = positions[c]["value"]
                sells.append({"code": c, "side": "sell", "all": True,
                              "reason": f"de-risking to {gross:.0%} gross ({why})"})
                sold.add(c)
                excess -= v
                evt.append(("derisk", c, positions[c].get("unrealized_pct", 0.0), why))

        orders = sells + buys      # sells fill first at the same open, funding the buys

        for c in list(self.peak):
            if c not in positions and c not in {b["code"] for b in buys}:
                self.peak.pop(c, None)

        sentiment = clamp(1.5 * score + 0.4 * (d["b"] - 0.5), -0.95, 0.95)
        mood = self._mood(regime, flipped, thrust, panic, own_dd, score)
        note = self._note(date, day, score, d, regime, flipped, gross, prev_gross, why,
                          evt, names, sec_raw, cands, positions, sold, equity, cash,
                          own_dd, thrust, panic, peers)
        return {"orders": orders, "sentiment": round(sentiment, 3), "mood": mood,
                "note": note}

    # -------------------------------------------------------------- narration
    @staticmethod
    def _mood(regime, flipped, thrust, panic, own_dd, score):
        if panic:
            return "hitting the brakes"
        if thrust:
            return "pressing the turn"
        if flipped:
            return "repositioning"
        if own_dd <= -0.08:
            return "grinding"
        return {"risk-on": "pressed", "constructive": "constructive",
                "defensive": "cautious", "risk-off": "in cash"}.get(regime, "measured")

    def _note(self, date, day, score, d, regime, flipped, gross, prev_gross, why, evt,
              names, sec_raw, cands, positions, sold, equity, cash, own_dd, thrust,
              panic, peers):
        def nm(c):
            return names.get(c, c)

        top_sec = max(sec_raw, key=lambda s: sec_raw[s]) if sec_raw else None
        bot_sec = min(sec_raw, key=lambda s: sec_raw[s]) if sec_raw else None
        n_pos = len([c for c in positions if c not in sold])
        buys = [e for e in evt if e[0] == "buy"]
        stops = [e for e in evt if e[0] == "stop"]
        rots = [e for e in evt if e[0] == "rot_out"]
        derisk = [e for e in evt if e[0] == "derisk"]

        if panic and (derisk or stops or gross < prev_gross):
            return (f"Circuit breaker: TASI {d['tret']:+.1%} with breadth at {d['b']:.0%}. "
                    f"I do not wait for a second print — gross {prev_gross:.0%} to "
                    f"{gross:.0%} at tomorrow's open. Score {score:+.2f} (trend "
                    f"{d['trend']:+.2f}, stress {d['stress']:.2f}). Being early on the way "
                    f"down costs a few basis points; being late costs quarters.")
        if thrust and buys:
            c = buys[0][1]
            return (f"Breadth thrust: {d['b']:.0%} above the 50d against {d['b20']:.0%} on "
                    f"the 20-session average, out of a washout {day - self.thrust_low_day} "
                    f"sessions ago. Forcing gross to {gross:.0%} before the 200d agrees. "
                    f"Leading with {nm(c)} (3m {buys[0][2]:+.1%}). Bottoms are made by "
                    f"participation, not by headlines.")
        if flipped and (buys or rots or derisk):
            return (f"Regime {self.prev_regime} to {regime}: score {score:+.2f} "
                    f"(trend {d['trend']:+.2f}, breadth {d['breadth']:+.2f}, mom "
                    f"{d['mom']:+.2f}, stress {d['stress']:.2f}). Gross {prev_gross:.0%} "
                    f"to {gross:.0%} across {len(rots) + len(derisk)} exits and "
                    f"{len(buys)} adds. The model moves the book; my opinion does not.")
        if stops:
            _t, c, upnl, reason = stops[0]
            n_more = len(stops) - 1
            extra = (f" {n_more} other name{'s' if n_more > 1 else ''} went with it."
                     if n_more else "")
            return (f"Stopped out of {nm(c)} at {upnl:+.1%} — {reason}. Benched for "
                    f"{self.p['bench_days']} sessions so I cannot re-buy my own mistake."
                    f"{extra} Book {n_pos} names, {1 - cash / equity:.0%} invested, equity "
                    f"SAR {equity:,.0f}.")
        if buys:
            _t, c, m3, sc = buys[0]
            secs = (f"{top_sec} leads on median 3/6m at {sec_raw[top_sec]:+.1%}, "
                    f"{bot_sec} trails at {sec_raw[bot_sec]:+.1%}. " if top_sec else "")
            return (f"Rotation into a {regime} tape ({score:+.2f}), gross target "
                    f"{gross:.0%}. {secs}Adding {nm(c)} — 3m {m3:+.1%}, composite "
                    f"{sc:+.2f}" + (f", plus {len(buys) - 1} more." if len(buys) > 1 else ".")
                    + f" Target weight {1.0 / max(1, self.p['max_names_on']):.0%}-ish a "
                      f"name, sized inverse to vol.")
        if rots or derisk:
            e = (rots or derisk)[0]
            tail = (f" {len(rots) + len(derisk) - 1} more went with it."
                    if len(rots) + len(derisk) > 1 else "")
            return (f"Cutting the book to fit the regime: out of {nm(e[1])} at "
                    f"{e[2]:+.1%} — {e[3] or why}.{tail} Score {score:+.2f}, breadth "
                    f"{d['b']:.0%}, target gross {gross:.0%} against "
                    f"{1 - cash / equity:.0%} invested. Rotation is not conviction, it is "
                    f"arithmetic.")

        self.note_idx += 1
        inv = 1.0 - cash / equity
        lead = cands[0] if cands else None
        quiet = [
            (f"Regime read {score:+.2f}: trend {d['trend']:+.2f}, breadth {d['b']:.0%} "
             f"({d['breadth']:+.2f}), momentum {d['mom']:+.2f}, stress {d['stress']:.2f}. "
             f"Gross {gross:.0%}, actually {inv:.0%} invested across {n_pos} names. "
             f"No change earns its commission today."),
            (f"Sector board: {top_sec} {sec_raw[top_sec]:+.1%} at the front, {bot_sec} "
             f"{sec_raw[bot_sec]:+.1%} at the back — a "
             f"{sec_raw[top_sec] - sec_raw[bot_sec]:.0%} spread on median 3/6m. That "
             f"spread is the whole business; the index return is a rounding error next "
             f"to it."
             if top_sec else
             f"Sector data too thin to rank today. Holding {n_pos} names, {inv:.0%} "
             f"invested, and no opinion I would pay commission for."),
            (f"TASI {d['dist_hi']:+.1%} from its 52-week high, breadth {d['b']:.0%} vs "
             f"{d['b20']:.0%} on the 20-session mean. Score {score:+.2f} keeps me at "
             f"{gross:.0%} gross. Waiting is a position and it is currently the right size."),
            (f"Book check: {n_pos} names, {inv:.0%} deployed, SAR {cash:,.0f} idle, equity "
             f"SAR {equity:,.0f}"
             + (f" ({own_dd:.1%} off my own high — the 7% stop is the line I do not "
                f"argue with)." if own_dd < -0.04 else ".")
             + (f" Best thing on the screen is {nm(lead['code'])} at composite "
                f"{lead['score']:+.2f}." if lead else "")),
            (f"Volatility and drawdown together read {d['stress']:.2f} of stress; the "
             f"trend leg is {d['trend']:+.2f}. Net {score:+.2f} — {regime}. Next scheduled "
             f"rotation in {max(0, self.p['rebal_every'] - (day - self.last_rebal))} "
             f"sessions unless the tape forces one sooner."),
            (f"Peer tape: {len(peers)} books visible, best trailing quarter among them "
             f"{max((q.get('ret_63') or 0.0) for q in peers.values()):+.1%}, average cash "
             f"{sum((q.get('cash_frac') or 0.0) for q in peers.values()) / len(peers):.0%}. "
             f"My score reads {score:+.2f}. Confirmation is welcome; instruction is not."
             if peers else
             f"No peer prints to cross-check today, so the model stands alone: score "
             f"{score:+.2f}, breadth {d['b']:.0%}, gross {gross:.0%}, {n_pos} names held."),
            (f"Breadth {d['b']:.0%} today against a 5-session mean of {d['b5']:.0%} and a "
             f"20-session mean of {d['b20']:.0%}. The slope, not the level, is what turns "
             f"first — and it currently reads {d['breadth']:+.2f}. Positioned {inv:.0%}."),
            (f"{'Holding fire' if gross <= 0.02 else 'Holding the line'} at {gross:.0%} "
             f"gross, {n_pos} names, equity SAR {equity:,.0f}. Nothing in the regime model "
             f"({score:+.2f}) argues for a different number, and I do not trade to feel "
             f"busy."),
        ]
        return quiet[self.note_idx % len(quiet)]


STRATEGY = Waqt()
