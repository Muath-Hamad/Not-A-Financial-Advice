"""Mizan — multi-factor quant, rebuilt aggressive.

Dr. Muteb's factor book had the right shape and the wrong dosage: over-diversified,
under-deployed, and taxed to death by a 16x annual turnover. Mizan keeps the science
and fixes the engineering.

The rulebook
------------
1. UNIVERSE. Whole main market. A name is investable when it has ~3 months of history
   (sma50 + ret_3m present) and traded at least SAR 2m a session. Everything is
   NaN-guarded; IPOs simply are not eligible until their indicators exist.

2. SCORE (cross-sectional z-blend, four sleeves, computed weekly):
     - trend quality  z(drawdown), z(px/sma200-1), z(dist_52w_high)   ~0.51
     - momentum       z(ret_6m - ret_1m), z(ret_6m)                   ~0.41
     - low volatility z(-vol_21)                                      ~0.04
     - mean reversion z(-ret_1w)                                      ~0.04
   Plus execution overrides: a penalty for parabolic weeks (ret_1w > 18%) and for
   RSI > 85, because paying up into a vertical print is a cost, not a factor.
   The low-vol sleeve is deliberately small in *selection* and carries its real
   weight in *sizing* — sleepy names rank badly but volatile names get sized down.

3. PEERS (bounded overlay). Names held by peers whose 63-day return beats both zero
   and the field median get up to +0.22 of a z-score. Only winners get a vote, the
   tilt is capped, and with no peers the book is unchanged — the overlay can improve
   the ranking, never define it.

4. BOOK. Top 9 ranks, conviction-tilted inverse-vol weights (rank 1 carries ~2x the
   tilt of rank 9), 22% hard cap per name, 40% cap per sector, position value capped
   at 10% of the name's daily turnover.

5. GROSS. Vol-targeted: an annualized book-sigma budget of 34% that lets gross sit at
   100% in any normal tape and only trims when the holdings themselves are turbulent.
   Two brakes, both built to almost never fire: a washout brake (index under its 200d
   AND breadth under 8% AND TASI 3m below -12%) and an own-equity circuit breaker at
   -28% from the high water mark. Every softer index-timing rule measured on this
   market was a pure fee — cash is not a hedge here, it is a fee.

6. TURNOVER. Weekly rebalance only, rank buffer of 31 (hold until a name is genuinely
   out of the running), 10% drift bands, minimum order size. Target ~6-7x gross
   annual turnover instead of 16x. At 13 bps a side that difference alone is ~2.5%
   a year, which is most of a factor premium.

7. STOPS. Wide only: -40% trailing from peak close. Tight ATR trails were measured
   and they cost money — the trend-quality sleeve already sells weakness, and it
   sells it without paying the spread twice.
"""

from __future__ import annotations

import math
from datetime import timedelta

from strategy_base import Strategy

# ------------------------------------------------------------------ parameters
N_TARGET = 9              # book slots
RANK_BUFFER = 31          # hold a name while it ranks inside this
MAX_W = 0.22              # hard cap per position
SECTOR_CAP = 0.40         # hard cap per sector
DRIFT_BAND = 0.10         # ignore target/actual gaps smaller than this
MIN_TURNOVER = 2.0e6      # SAR/session to be investable
LIQ_CAP = 0.10            # position value <= this fraction of daily turnover
CONV_TILT = 1.0           # rank-1 gets (1 + CONV_TILT)x the inverse-vol weight
VOL_POW = 0.5             # inverse-vol exponent for sizing
VOL_LO, VOL_HI = 0.15, 0.50
VOL_BUDGET = 0.34         # annualized book sigma budget
RHO = 0.45                # assumed average pairwise correlation
GROSS_FLOOR = 0.45
CRISIS_GROSS = 0.70       # washout brake: rare by design
CRISIS_BREADTH = 0.08
CRISIS_TASI_3M = -0.12
EQUITY_DD_LIMIT = -0.28   # own-equity drawdown circuit breaker
EQUITY_DD_GROSS = 0.60
DISASTER_TRAIL = 0.40     # exit a name this far below its peak close
BLOCK_SESSIONS = 15       # cooldown after a disaster exit
MIN_REBAL_GAP = 4         # sessions
PEER_TILT = 0.22          # max z-score bonus from the winning peers' books

W_DD, W_P200, W_D52 = 0.22, 0.19, 0.10
W_M61, W_M6 = 0.21, 0.20
W_LVOL, W_REV = 0.04, 0.04

SPIKE_RET1W = 0.18
SPIKE_PENALTY = 0.30
HOT_RSI = 85.0
HOT_PENALTY = 0.20


def ok(x) -> bool:
    return isinstance(x, (int, float)) and x == x and not math.isinf(x)


def num(x, default=0.0) -> float:
    return float(x) if ok(x) else default


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def zmap(vals):
    """Z-score a list, clipped to +-3. Returns zeros if degenerate."""
    n = len(vals)
    if n < 3:
        return [0.0] * n
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / n
    sd = math.sqrt(var)
    if sd < 1e-12:
        return [0.0] * n
    return [clamp((v - mu) / sd, -3.0, 3.0) for v in vals]


class Mizan(Strategy):
    meta = {
        "handle": "mizan",
        "name": "Mizan",
        "emoji": "⚖️",
        "tagline": "Four sleeves, nine names, one balance sheet. Turnover is the enemy.",
        "risk_style": "aggressive systematic multi-factor",
        "color": "#888888",
        "character": (
            "A multi-factor portfolio manager who rebuilt the family factor book after "
            "watching a previous generation diversify and over-trade its edge to nothing. "
            "She scores the whole market on trend quality, momentum, volatility and "
            "reversal, concentrates nine conviction-weighted positions, and defends the "
            "turnover budget like it is her own money — because in this competition it is."
        ),
    }

    def __init__(self):
        self.week_key = None
        self.week_no = 0
        self.last_rebal_day = -99
        self.peak = {}            # code -> peak close while held
        self.blocked = {}         # code -> day_index of disaster exit
        self.rank = {}            # last computed ranking
        self.score = {}
        self.n_eligible = 0
        self.gross_target = 1.0
        self.vol_scalar = 1.0
        self.est_vol = 0.0
        self.crisis = False
        self.note_turn = 0
        self.last_peer_note = -99
        self.peer_leader = None
        self.peer_overlap = 0.0
        self.eq_peak = 0.0
        self.eq_dd = 0.0

    # ------------------------------------------------------------------ regime
    def _regime(self, view, ctx):
        """Crisis brake only. Everything softer than a crisis stays fully invested."""
        t = view.get("TASI") or {}
        c = t.get("AdjClose")
        c = num(c if ok(c) else t.get("Close"), float("nan"))
        s200 = num(t.get("sma200"), float("nan"))
        s100 = num(t.get("sma100"), float("nan"))
        r3 = num(t.get("ret_3m"), 0.0)
        breadth = num(ctx.get("breadth_sma50"), 0.5)
        below200 = ok(c) and ok(s200) and c < s200
        below100 = ok(c) and ok(s100) and c < s100
        crisis = bool(below200 and breadth < CRISIS_BREADTH and r3 < CRISIS_TASI_3M)
        # a health score purely for the journal / sentiment, never for sizing
        health = 0.0
        if ok(c) and ok(s100):
            health += 0.35 if c > s100 else -0.35
        if ok(c) and ok(s200):
            health += 0.25 if c > s200 else -0.25
        health += 1.2 * (breadth - 0.5)
        health += clamp(4.0 * r3, -0.4, 0.4)
        return crisis, clamp(health, -1.0, 1.0), breadth, below100, below200, r3

    # ------------------------------------------------------------------- peers
    def _peer_consensus(self, ctx):
        """Weight-of-book from peers who are actually beating the field."""
        peers = ctx.get("peers") or {}
        if not peers:
            self.peer_leader = None
            return {}
        rets = []
        for h, p in peers.items():
            r = p.get("ret_63")
            if r is None:
                r = p.get("ret_21", 0.0)
            rets.append((num(r, 0.0), h))
        if not rets:
            return {}
        rets.sort()
        med = rets[len(rets) // 2][0]
        self.peer_leader = rets[-1][1]
        bar = max(0.0, med)
        cons, tot = {}, 0.0
        for r, h in rets:
            if r <= bar:
                continue
            wgt = clamp(r * 4.0, 0.0, 1.0)
            if wgt <= 0.0:
                continue
            tot += wgt
            for c, ww in (peers[h].get("positions") or {}).items():
                cons[c] = cons.get(c, 0.0) + wgt * num(ww, 0.0)
        if tot <= 0.0:
            return {}
        return {c: v / tot for c, v in cons.items()}

    # ------------------------------------------------------------------ scoring
    def _rank_market(self, view, ctx):
        rows = []
        for c, r in view.items():
            if c == "TASI" or not isinstance(r, dict):
                continue
            px = r.get("Close")
            if not (ok(px) and px > 0.5):
                continue
            if not ok(r.get("sma50")) or not ok(r.get("ret_3m")):
                continue
            # liquidity on a 20-session average, not a single print: this tape has
            # ~50 sessions where the whole market reports zero volume, and a one-day
            # measure would quietly make the entire market uninvestable that day.
            v20 = r.get("vol_sma20")
            turn = v20 * px if (ok(v20) and v20 > 0) else 0.0
            t1 = r.get("turnover_sar")
            if ok(t1) and t1 > turn:
                turn = float(t1)
            if turn < MIN_TURNOVER:
                continue
            rows.append((c, r, float(turn)))
        if len(rows) < N_TARGET + 3:
            return {}, {}, {}
        self.n_eligible = len(rows)

        dd, p200, d52, m61, m6, lvol, rev = [], [], [], [], [], [], []
        for c, r, _t in rows:
            # every indicator in this feed is built on AdjClose, so price-vs-average
            # comparisons must use AdjClose too. Mixing raw Close into an AdjClose
            # moving average silently prices in dividends that have not been paid yet.
            px = r.get("AdjClose")
            px = float(px) if (ok(px) and px > 0) else float(r["Close"])
            r3 = num(r.get("ret_3m"), 0.0)
            r6 = r.get("ret_6m")
            r6 = float(r6) if ok(r6) else 2.0 * r3
            r1m = num(r.get("ret_1m"), 0.0)
            s200 = r.get("sma200")
            s100 = r.get("sma100")
            s50 = float(r["sma50"])
            if ok(s200) and s200 > 0:
                trend = px / float(s200) - 1.0
            elif ok(s100) and s100 > 0:
                trend = px / float(s100) - 1.0
            else:
                trend = px / s50 - 1.0
            dd.append(num(r.get("drawdown"), -0.30))
            p200.append(clamp(trend, -0.90, 3.0))
            d52.append(num(r.get("dist_52w_high"), -0.40))
            m61.append(r6 - r1m)
            m6.append(r6)
            lvol.append(-num(r.get("vol_21"), 0.30))
            rev.append(-num(r.get("ret_1w"), 0.0))

        z_dd, z_p2, z_d5 = zmap(dd), zmap(p200), zmap(d52)
        z_61, z_6 = zmap(m61), zmap(m6)
        z_lv, z_rv = zmap(lvol), zmap(rev)

        cons = self._peer_consensus(ctx)
        score, meta = {}, {}
        for i, (c, r, turn) in enumerate(rows):
            s = (W_DD * z_dd[i] + W_P200 * z_p2[i] + W_D52 * z_d5[i]
                 + W_M61 * z_61[i] + W_M6 * z_6[i]
                 + W_LVOL * z_lv[i] + W_REV * z_rv[i])
            r1w = r.get("ret_1w")
            if ok(r1w) and r1w > SPIKE_RET1W:
                s -= SPIKE_PENALTY
            rsi = r.get("rsi14")
            if ok(rsi) and rsi > HOT_RSI:
                s -= HOT_PENALTY
            if cons:
                s += PEER_TILT * clamp(cons.get(c, 0.0) / 0.15, 0.0, 1.0)
            score[c] = s
            meta[c] = (r, turn)
        ranked = sorted(score, key=lambda c: (-score[c], c))
        rank = {c: i + 1 for i, c in enumerate(ranked)}
        self.peer_overlap = float(len(cons))
        return score, rank, meta

    # ------------------------------------------------------------------ sizing
    def _targets(self, sel, meta, gross, equity, sectors):
        raws = {}
        n = len(sel)
        for i, c in enumerate(sel):
            r = meta[c][0]
            v = num(r.get("vol_21"), 0.30)
            v = clamp(v if v > 0 else 0.30, VOL_LO, VOL_HI)
            tilt = 1.0 + CONV_TILT * (n - i - 1) / max(1, n - 1)
            raws[c] = (v ** (-VOL_POW)) * tilt
        tot = sum(raws.values())
        if tot <= 0:
            return {}, 0.0
        base = {c: raws[c] / tot for c in raws}

        # vol targeting: book sigma under a budget, gross still reaches 100%
        wavg = 0.0
        for c in base:
            v = num(meta[c][0].get("vol_21"), 0.30)
            wavg += base[c] * clamp(v if v > 0 else 0.30, VOL_LO, 0.60)
        diversify = math.sqrt(RHO + (1.0 - RHO) / max(1, n))
        est = wavg * diversify
        self.est_vol = est
        self.vol_scalar = clamp(VOL_BUDGET / est, GROSS_FLOOR, 1.0) if est > 1e-6 else 1.0
        g = gross * self.vol_scalar * (n / float(N_TARGET))
        g = clamp(g, 0.0, 1.0)

        tgt = {c: g * base[c] for c in base}
        # per-name cap, liquidity cap, then sector cap; redistribute what fits
        for _ in range(5):
            excess = 0.0
            free = []
            for c in list(tgt):
                cap = MAX_W
                liq = LIQ_CAP * meta[c][1] / equity if equity > 0 else MAX_W
                cap = min(cap, max(0.02, liq))
                if tgt[c] > cap:
                    excess += tgt[c] - cap
                    tgt[c] = cap
                else:
                    free.append(c)
            if excess <= 1e-6 or not free:
                break
            add = excess / len(free)
            for c in free:
                tgt[c] += add
        for _ in range(4):
            bys = {}
            for c in tgt:
                bys.setdefault(sectors.get(c, "Other"), []).append(c)
            worst = None
            for s_, cs in bys.items():
                tot_s = sum(tgt[c] for c in cs)
                if tot_s > SECTOR_CAP + 1e-9:
                    worst = (s_, cs, tot_s)
                    break
            if worst is None:
                break
            s_, cs, tot_s = worst
            for c in cs:
                tgt[c] *= SECTOR_CAP / tot_s
        return tgt, g

    # ------------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0))
        names = ctx.get("names", {})
        sectors = ctx.get("sectors", {})
        positions = portfolio.get("positions", {}) or {}
        cash = num(portfolio.get("cash"), 0.0)
        equity = max(num(portfolio.get("equity"), 1.0), 1.0)
        tret = num(ctx.get("tasi_ret_1d"), 0.0)
        eqh = ctx.get("equity_history") or []
        my_ret = (eqh[-1] / eqh[-2] - 1.0) if len(eqh) >= 2 and eqh[-2] else 0.0
        if equity > self.eq_peak:
            self.eq_peak = equity
        eq_dd = (equity / self.eq_peak - 1.0) if self.eq_peak > 0 else 0.0
        self.eq_dd = eq_dd

        crisis, health, breadth, below100, below200, t3 = self._regime(view, ctx)
        self.crisis = crisis

        orders, sells, buys = [], [], []
        events = []

        # ---- daily: peaks and the wide disaster trail --------------------
        for c in list(self.peak):
            if c not in positions:
                self.peak.pop(c, None)
        for c, p in positions.items():
            r = view.get(c)
            if not isinstance(r, dict):
                continue
            px = r.get("AdjClose")
            if not (ok(px) and px > 0):
                px = r.get("Close")
            if not (ok(px) and px > 0):
                continue
            px = float(px)
            pk = self.peak.get(c, float(px))
            if px > pk:
                pk = float(px)
            self.peak[c] = pk
            if pk > 0 and px < pk * (1.0 - DISASTER_TRAIL):
                sells.append({"code": c, "side": "sell", "all": True,
                              "reason": (f"disaster trail: {px:.2f} is {px / pk - 1:+.0%} "
                                         f"off its {pk:.2f} peak")})
                self.blocked[c] = day
                events.append(("disaster", c, num(p.get("unrealized_pct"), 0.0), px / pk - 1.0))

        # ---- weekly cadence ----------------------------------------------
        try:
            ic = (date + timedelta(days=1)).isocalendar()
            wkey = (int(ic[0]), int(ic[1]))
        except Exception:
            wkey = (day // 5, 0)
        rebal = (wkey != self.week_key) and (day - self.last_rebal_day >= MIN_REBAL_GAP)

        n_add = n_cut = n_trim = 0
        top_add = None
        cut_info = None
        weakest = None
        sel = []
        score = rank = meta = None
        if rebal:
            score, rank, meta = self._rank_market(view, ctx)
            if not score:
                # A dead tape (holiday print, zero volume market-wide) is not a
                # rebalance. Leave the window open and try again next session
                # rather than losing the week to a data artefact.
                rebal = False
            else:
                self.week_key = wkey
                self.week_no += 1
                self.last_rebal_day = day
                self.score, self.rank = score, rank

        if rebal:
            gross = CRISIS_GROSS if crisis else 1.0
            if eq_dd <= EQUITY_DD_LIMIT:
                gross = min(gross, EQUITY_DD_GROSS)
            self.gross_target = gross
            stopped = {o["code"] for o in sells}

            if score:
                held = [c for c in positions if c not in stopped]
                keep = [c for c in held if rank.get(c, 10 ** 6) <= RANK_BUFFER]
                sel = list(keep)
                for c in sorted(score, key=lambda x: (-score[x], x)):
                    if len(sel) >= N_TARGET:
                        break
                    if c in sel or c in stopped:
                        continue
                    if day - self.blocked.get(c, -999) < BLOCK_SESSIONS:
                        continue
                    if not isinstance(view.get(c), dict):
                        continue
                    sel.append(c)
                sel.sort(key=lambda c: (-score.get(c, -9.0), c))
                sel = sel[:N_TARGET]

                tgt, g = self._targets(sel, meta, gross, equity, sectors)

                # exits: out of the book entirely
                proceeds = 0.0
                for c in held:
                    if c in tgt:
                        continue
                    if not isinstance(view.get(c), dict):
                        continue  # halted, cannot price it, leave it alone
                    rk = rank.get(c)
                    why = (f"rank #{rk} of {len(rank)} — outside the {RANK_BUFFER} buffer"
                           if rk else "dropped out of the investable set")
                    sells.append({"code": c, "side": "sell", "all": True, "reason": why})
                    proceeds += num(positions[c].get("value"), 0.0)
                    n_cut += 1
                    if cut_info is None:
                        cut_info = (c, rk, num(positions[c].get("unrealized_pct"), 0.0))

                # trims: above target by more than the band
                for c in sel:
                    if c not in positions or not isinstance(view.get(c), dict):
                        continue
                    cw = num(positions[c].get("weight"), 0.0)
                    tw = tgt.get(c, 0.0)
                    if cw > tw + DRIFT_BAND and cw > 0:
                        frac = clamp((cw - tw) / cw, 0.05, 0.95)
                        sells.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                      "reason": f"trim {cw:.1%} to target {tw:.1%}"})
                        proceeds += frac * num(positions[c].get("value"), 0.0)
                        n_trim += 1
                    if weakest is None or rank.get(c, 0) > rank.get(weakest, 0):
                        weakest = c

                # buys: fill the gaps, best conviction first, inside the cash budget
                min_order = max(2000.0, 0.012 * equity)
                budget = cash + proceeds * 0.9975 - 0.004 * equity
                for c in sel:
                    if not isinstance(view.get(c), dict):
                        continue
                    cw = num(positions.get(c, {}).get("weight"), 0.0)
                    tw = tgt.get(c, 0.0)
                    if tw - cw <= DRIFT_BAND and cw > 0:
                        continue
                    gap = (tw - cw) * equity
                    if gap < min_order or budget < min_order:
                        continue
                    amt = min(gap, budget)
                    r = view[c]
                    buys.append({"code": c, "side": "buy", "sar": round(amt, 2),
                                 "reason": (f"rank #{rank.get(c, 0)}, z {score.get(c, 0.0):+.2f}, "
                                            f"6m {num(r.get('ret_6m'), 0.0):+.0%}, dd "
                                            f"{num(r.get('drawdown'), 0.0):+.0%}, sigma "
                                            f"{num(r.get('vol_21'), 0.0):.0%} -> {tw:.1%}")})
                    budget -= amt * 1.0015
                    n_add += 1
                    if top_add is None:
                        top_add = (c, r, score.get(c, 0.0), rank.get(c, 0), tw)
        else:
            # mid-week: only defend the hard cap, nothing else costs money
            for c, p in positions.items():
                w = num(p.get("weight"), 0.0)
                if w > MAX_W + 0.06 and isinstance(view.get(c), dict):
                    frac = clamp((w - MAX_W) / w, 0.05, 0.9)
                    sells.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                  "reason": f"drift {w:.1%} through the {MAX_W:.0%} cap"})

        orders = sells + buys
        invested = 1.0 - cash / equity if equity > 0 else 0.0

        # ---------------------------------------------------------- sentiment
        sentiment = clamp(0.75 * health + 8.0 * clamp(tret, -0.03, 0.03), -0.9, 0.9)
        if crisis:
            sentiment = min(sentiment, -0.45)

        if crisis:
            mood = "risk-budget cut"
        elif events:
            mood = "enforcing the trail"
        elif rebal and (n_add or n_cut or n_trim):
            mood = "rebalancing"
        elif rebal:
            mood = "declining to trade"
        elif tret <= -0.02:
            mood = "unbothered"
        elif health > 0.35 and invested > 0.85:
            mood = "fully deployed"
        elif invested < 0.5:
            mood = "underweight, by construction"
        else:
            mood = "systematic"

        note = self._note(day, names, ctx, positions, equity, cash, invested,
                          tret, my_ret, breadth, health, crisis, rebal, n_add, n_cut,
                          n_trim, top_add, cut_info, weakest, events, below200, t3)

        return {"orders": orders, "sentiment": round(sentiment, 3),
                "mood": mood, "note": note}

    # -------------------------------------------------------------- journal
    def _note(self, day, names, ctx, positions, equity, cash, invested,
              tret, my_ret, breadth, health, crisis, rebal, n_add, n_cut, n_trim,
              top_add, cut_info, weakest, events, below200, t3):
        nm = lambda c: names.get(c, c)
        peers = ctx.get("peers") or {}

        for kind, c, upnl, off in events:
            return (f"Disaster trail fired on {nm(c)}: {off:+.0%} from its peak close, out at "
                    f"{upnl:+.1%}. That trail sits at -{DISASTER_TRAIL:.0%} precisely so it "
                    f"almost never fires — the factor score is supposed to sell weakness "
                    f"before a stop has to. This one got away from the model.")

        if rebal and (n_add or n_cut or n_trim):
            head = (f"W{self.week_no}: {n_add} adds, {n_cut} exits, {n_trim} trims. "
                    f"Gross target {self.gross_target * self.vol_scalar:.0%} "
                    f"(book sigma {self.est_vol:.0%} vs a {VOL_BUDGET:.0%} budget), "
                    f"{self.n_eligible} names passed the SAR {MIN_TURNOVER / 1e6:.0f}m "
                    f"liquidity screen.")
            if top_add is not None:
                c, r, s, rk, tw = top_add
                head += (f" Top add {nm(c)} at #{rk}: z {s:+.2f}, 6m "
                         f"{num(r.get('ret_6m'), 0.0):+.0%}, {num(r.get('drawdown'), 0.0):+.0%} "
                         f"off its high, RSI {num(r.get('rsi14'), 50.0):.0f} -> {tw:.0%} weight.")
            elif cut_info is not None:
                c, rk, upnl = cut_info
                head += (f" Biggest change is the exit: {nm(c)} slipped to "
                         f"#{rk if rk else '-'}, realised {upnl:+.1%}.")
            if crisis:
                head += f" Washout brake armed, so the whole book is scaled to {CRISIS_GROSS:.0%}."
            elif self.eq_dd <= EQUITY_DD_LIMIT:
                head += (f" Equity {self.eq_dd:+.0%} off its high — circuit breaker holds gross "
                         f"at {EQUITY_DD_GROSS:.0%} until it heals.")
            return head[:495]

        if crisis:
            return (f"Washout brake engaged: index below its 200d, breadth {breadth:.0%}, TASI 3m "
                    f"{t3:+.1%}. Gross target {CRISIS_GROSS:.0%}. This is the only index rule in "
                    f"the book and it is built to almost never fire — every softer version of "
                    f"market timing I measured on this index cost money. Equity SAR {equity:,.0f}, "
                    f"{invested:.0%} invested.")

        if self.eq_dd <= EQUITY_DD_LIMIT:
            return (f"Circuit breaker: equity {self.eq_dd:+.1%} below its high water mark, so gross "
                    f"is capped at {EQUITY_DD_GROSS:.0%} regardless of what the ranking says. "
                    f"Book SAR {equity:,.0f}, {len(positions)} names, {invested:.0%} invested. "
                    f"Survival first, then the factors get their leash back.")

        if rebal:
            if not positions:
                return (f"W{self.week_no} review, flat book. {self.n_eligible} names cleared "
                        f"liquidity, none of the top {N_TARGET} could be funded or cleared the "
                        f"cooldowns. Breadth {breadth:.0%}, TASI 3m {t3:+.1%}. Cash earns "
                        f"nothing, but neither does a forced trade.")
            wk = f"{nm(weakest)} at #{self.rank.get(weakest, 0)}" if weakest else "n/a"
            variants = [
                (f"W{self.week_no}: zero trades. All {len(positions)} holdings sit inside the "
                 f"rank-{RANK_BUFFER} buffer (weakest {wk}) and every weight is within the "
                 f"{DRIFT_BAND:.0%} drift band. Turnover at 13 bps a side is the one cost I "
                 f"control absolutely, so I decline to pay it."),
                (f"W{self.week_no} review: nothing to do. Gross {invested:.0%}, "
                 f"{len(positions)} names, weakest link {wk}. The previous generation of this "
                 f"book traded 16x a year and handed roughly four points of annual return to "
                 f"the broker. I run six."),
                (f"W{self.week_no}: book unchanged. Breadth {breadth:.0%}, index "
                 f"{'below' if below200 else 'above'} its 200d, my estimated book sigma "
                 f"{self.est_vol:.0%}. Rebalancing into unchanged rankings is activity, not "
                 f"alpha."),
            ]
            return variants[self.week_no % len(variants)][:495]

        if tret <= -0.02:
            worst_c, worst_u = None, 9.9
            for c, p in positions.items():
                u = num(p.get("unrealized_pct"), 0.0)
                if u < worst_u:
                    worst_c, worst_u = c, u
            tail = (f"Weakest holding {nm(worst_c)} at {worst_u:+.1%}." if worst_c
                    else "No positions to defend.")
            return (f"TASI {tret:+.1%}, book {my_ret:+.1%} at {invested:.0%} gross across "
                    f"{len(positions)} names. {tail} Nothing in the rulebook reacts to a single "
                    f"session — the ranking is recomputed Sunday and not a day before.")

        if peers and day - self.last_peer_note >= 25:
            self.last_peer_note = day
            lead = self.peer_leader
            if lead and lead in peers:
                p = peers[lead]
                pr = num(p.get("ret_63"), 0.0)
                pcash = num(p.get("cash_frac"), 0.0)
                pos = p.get("positions") or {}
                shared = [c for c in pos if c in positions]
                top = max(pos, key=lambda c: num(pos.get(c), 0.0)) if pos else None
                return (f"Field check: {lead} leads on 63-day return at {pr:+.1%}, "
                        f"{pcash:.0%} cash"
                        + (f", biggest position {nm(top)} which my model ranks "
                           f"#{self.rank.get(top, 0) or '-'}" if top else "")
                        + f". We overlap on {len(shared)} name(s). Their book earns at most "
                          f"{PEER_TILT:.2f} of a z-score in my ranking — a tilt, not a mandate.")[:495]

        top_c = None
        if positions:
            top_c = max(positions, key=lambda c: num(positions[c].get("weight"), 0.0))
        self.note_turn += 1
        variants = [
            (f"Regime health {health:+.2f} on {breadth:.0%} breadth; gross {invested:.0%} across "
             f"{len(positions)} names, SAR {cash:,.0f} idle. The vol budget only bites when the "
             f"book's own sigma clears {VOL_BUDGET:.0%} — it prints {self.est_vol:.0%} today, so "
             f"we stay fully deployed."),
            (f"Position check: largest weight "
             + (f"{nm(top_c)} at {num(positions[top_c].get('weight'), 0.0):.1%} "
                f"({num(positions[top_c].get('unrealized_pct'), 0.0):+.1%})" if top_c else "n/a")
             + f" against a {MAX_W:.0%} cap. Nine slots, conviction-tilted — the rank-1 name "
               f"carries roughly twice the tilt of rank 9. Diversification past ten names "
               f"measured as pure dilution."),
            (f"{self.n_eligible} names cleared the liquidity screen at the last ranking. The "
             f"score is {W_DD + W_P200 + W_D52:.0%} trend quality, {W_M61 + W_M6:.0%} momentum, "
             f"and a token {W_LVOL + W_REV:.0%} to low-vol and reversal — the low-vol sleeve "
             f"earns its keep in sizing, not selection. Book {invested:.0%}, P&L {my_ret:+.2%} "
             f"vs TASI {tret:+.2%}."),
            (f"Daily: TASI {tret:+.2%}, book {my_ret:+.2%}, gross {invested:.0%}. No rebalance "
             f"window, no cap breach, no trail hit — so no orders. Most days the correct "
             f"output of a factor model is silence."),
            (f"Risk note: estimated book sigma {self.est_vol:.0%} annualized against a "
             f"{VOL_BUDGET:.0%} budget, {len(positions)} positions, sector cap {SECTOR_CAP:.0%}. "
             f"Equity SAR {equity:,.0f}, drawdown discipline handled by the ranking rather than "
             f"tight stops — I tested tight stops and they cost more than they saved."),
            (f"Breadth {breadth:.0%}, index {'below' if below200 else 'above'} the 200d, TASI 3m "
             f"{t3:+.1%}. I hold {len(positions)} names and I am not trading on any of that: "
             f"the only index rule in this book is the crisis brake, and it is not armed."),
        ]
        return variants[self.note_turn % len(variants)][:495]


STRATEGY = Mizan()
