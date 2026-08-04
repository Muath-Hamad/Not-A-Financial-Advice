"""Hikma — quality compounding that learned to steer.

Um Khalid proved patience collects dividends; season 2 proved patience alone
does not compound when the index goes nowhere. Hikma keeps the philosophy —
own durable, liquid, cash-returning businesses and let them work — but adds
the three things she never had: a definition of quality that the tape has to
keep re-earning, an accumulation schedule that leans into what is working,
and a breadth valve that takes risk off the table before the ledger does.

Mechanism (general rulebook, no dates and no per-ticker plans):

  1. ELIGIBILITY (the "quality gate"). A name may be owned only if it has a
     full year of price history, trades above its own 200-day mean, clears a
     liquidity floor (60-session average turnover, also scaled to the size of
     the intended position), and is not a volatility carnival (ATR% cap).
  2. RANKING. Cross-sectional percentile blend:
        0.50 * rank(ret_12m)              durable price compounding
      + 0.50 * rank(ret_6m)               the medium-term leg still working
      + 0.20 * rank(trailing dividend yield)   cash actually returned
      + 0.30 * rank(persistence above sma200)  quality of the trend, not its slope
     Dividend and persistence terms fade in from neutral while their own
     look-back windows fill, so early-sim noise cannot distort the book.
     Peer books (public track records) add a small, capped tilt toward names
     the profitable agents also own; with no peers the term is exactly zero.
  3. ACCUMULATION. Weekly, targets are equal-weight across the top 9, scaled
     by the exposure the valve allows. The book moves only part of the way to
     target each week (70% up, 50% down) — averaged in, never a full reset, so
     a compounder is added to on strength and released gradually, not whipsawed
     out on one bad print.
  4. HARVEST. Extreme overextension (RSI > 82, above the upper Bollinger band,
     and >45% above its own 200-day mean) gets a 35% trim, once a month at
     most. Euphoria is a dividend the market pays in advance.
  5. RISK VALVE. Gross exposure is a continuous function of market breadth —
     full at 40% of the universe above its 50-day mean, tapering to 70% gross
     by the time breadth reaches 24% — with a hard cap at 60% gross whenever
     the book itself is more than 18% below its high-water mark. Checked every
     session against a 10-point band, so the valve steers instead of lurching,
     and the same daily check pushes idle cash (dividends included) back into
     the top of the ranking as soon as the book is under-deployed.
"""

from __future__ import annotations

from collections import deque

from strategy_base import Strategy

# ---------------------------------------------------------------- parameters
N_SLOTS = 9             # target number of compounders held
MAX_W = 0.16           # hard cap on any single name
MIN_TURNOVER = 3.0e6     # SAR, 60-session average, absolute liquidity floor
TURNOVER_MULT = 50.0     # position must be <= 1/50th of average daily turnover
MAX_ATR_PCT = 0.06       # no volatility carnivals in a compounding book
A_UP = 0.70             # weekly step toward a larger target (accumulate briskly)
A_DN = 0.50             # weekly step toward a smaller target (release gradually)
DUST_W = 0.008           # below this an exiting position is closed outright
BAND = 0.10             # exposure tolerance before the valve acts
MIN_BUY = 1200.0         # SAR, no dust orders
MIN_SELL = 900.0
TV_WIN = 60              # sessions in the turnover average
PERS_WIN = 252           # sessions in the persistence window
DIV_WIN = 252            # sessions in the trailing-dividend window
PERS_MIN = 40            # minimum observations before persistence is used
BREADTH_FULL = 0.40      # breadth at/above this -> fully invested
BREADTH_MIN = 0.24       # breadth at/below this -> minimum gross exposure
EXPO_MIN = 0.70          # gross exposure when participation has collapsed
DD_TRIGGER = -0.18       # own drawdown from the high-water mark that forces caution
EXPO_DD = 0.60          # gross cap while the book is repairing a drawdown
HARVEST_RSI = 82.0
HARVEST_EXT = 1.45       # times sma200
HARVEST_CUT = 0.35
W_R12 = 0.50             # rank weight: 12-month price compounding
W_R6 = 0.50              # rank weight: 6-month leg still working
W_DY = 0.20              # rank weight: trailing dividend yield
W_PERS = 0.30            # rank weight: persistence above the 200-day mean
PEER_TILT = 0.60         # multiplier on peer crowding, capped below
PEER_TILT_CAP = 0.10


def ok(x) -> bool:
    """True if x is a usable finite number (guards None/NaN/inf)."""
    return isinstance(x, (int, float)) and x == x and -1e30 < x < 1e30


def pct_ranks(pairs):
    """Average-tie percentile ranks. pairs: list of (value, code)."""
    n = len(pairs)
    out = {}
    if n == 0:
        return out
    pairs.sort(key=lambda t: t[0])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j + 2) / 2.0 / n          # average rank, 1-based, normalised
        for k in range(i, j + 1):
            out[pairs[k][1]] = r
        i = j + 1
    return out


class Hikma(Strategy):
    meta = {
        "handle": "hikma",
        "name": "Hikma",
        "emoji": "🏛️",
        "tagline": "Own the compounders. Steer the exposure. Collect the cash.",
        "character": (
            "A quality-compounding manager who treats a portfolio like an endowment "
            "with a pulse: durable, liquid, cash-returning businesses at the core, "
            "accumulated in slices rather than lumps. She is unsentimental about a "
            "name that stops earning its place, and she would rather hold 50% cash "
            "for a quarter than explain a 40% drawdown to anyone."
        ),
        "risk_style": "quality core with an active exposure valve",
        "color": "#888888",
    }

    def __init__(self):
        # rolling state, all built forward from observed data only
        self.tv = {}          # code -> deque of turnover_sar
        self.tv_sum = {}      # code -> running sum
        self.ab = {}          # code -> deque of 1/0 above sma200
        self.ab_sum = {}
        self.dv = {}          # code -> deque of per-share dividends
        self.dv_sum = {}
        self.prev_date = None
        self.last_rank = []   # cached ranked candidate list [(score, code)]
        self.div_total = 0.0
        self.harvest_lock = {}   # code -> day_index of last trim
        self.peak_equity = 0.0
        self.risk_off = False
        self.risk_off_days = 0

    # ------------------------------------------------------------- state keep
    def _update_state(self, view, day):
        for code, r in view.items():
            if code == "TASI":
                continue
            tv = r.get("turnover_sar")
            d = self.tv.get(code)
            if d is None:
                d = self.tv[code] = deque()
                self.tv_sum[code] = 0.0
            if ok(tv) and tv >= 0.0:
                d.append(tv)
                self.tv_sum[code] += tv
                while len(d) > TV_WIN:
                    self.tv_sum[code] -= d.popleft()

            px = r.get("AdjClose")
            s200 = r.get("sma200")
            a = self.ab.get(code)
            if a is None:
                a = self.ab[code] = deque()
                self.ab_sum[code] = 0.0
            if ok(px) and ok(s200) and s200 > 0:
                v = 1.0 if px > s200 else 0.0
                a.append(v)
                self.ab_sum[code] += v
                while len(a) > PERS_WIN:
                    self.ab_sum[code] -= a.popleft()

            dd = self.dv.get(code)
            if dd is None:
                dd = self.dv[code] = deque()
                self.dv_sum[code] = 0.0
            div = r.get("Dividends")
            dd.append(div if (ok(div) and div > 0) else 0.0)
            self.dv_sum[code] += dd[-1]
            while len(dd) > DIV_WIN:
                self.dv_sum[code] -= dd.popleft()

    def _tv_avg(self, code):
        d = self.tv.get(code)
        if not d:
            return 0.0
        return self.tv_sum[code] / len(d)

    # ------------------------------------------------------------- ranking
    def _rank_candidates(self, view, day, equity, peers):
        """Return sorted [(score, code, row)] of eligible quality compounders."""
        r12_p, r6_p, dy_p, pe_p = [], [], [], []
        rows = {}
        for code, r in view.items():
            if code == "TASI":
                continue
            px = r.get("AdjClose")
            if not ok(px) or px <= 0:
                continue
            rows[code] = r
            v = r.get("ret_12m")
            if ok(v):
                r12_p.append((v, code))
            v = r.get("ret_6m")
            if ok(v):
                r6_p.append((v, code))
            dy_p.append((self.dv_sum.get(code, 0.0) / px, code))
            a = self.ab.get(code)
            if a is not None and len(a) >= PERS_MIN:
                pe_p.append((self.ab_sum[code] / len(a), code))
        R12 = pct_ranks(r12_p)
        R6 = pct_ranks(r6_p)
        RDY = pct_ranks(dy_p)
        RPE = pct_ranks(pe_p)

        # look-back windows fade in from neutral so early sessions cannot
        # manufacture false "quality"
        f_dy = min(1.0, (day + 1) / float(DIV_WIN))
        f_pe = min(1.0, (day + 1) / 120.0)

        # peer tilt: names owned by the peers who are actually making money
        crowd = {}
        if peers:
            scored = [(p.get("ret_63", 0.0) or 0.0, h, p) for h, p in peers.items()]
            scored.sort(key=lambda t: -t[0])
            lead = [p for s, h, p in scored[: max(1, len(scored) // 2)] if s > 0]
            if lead:
                for p in lead:
                    for c, w in (p.get("positions") or {}).items():
                        if ok(w):
                            crowd[c] = crowd.get(c, 0.0) + float(w)
                for c in crowd:
                    crowd[c] /= len(lead)

        pos_val = equity / float(N_SLOTS)
        liq_floor = max(MIN_TURNOVER, TURNOVER_MULT * pos_val)
        out = []
        for code, r in rows.items():
            if not ok(r.get("ret_12m")):
                continue                       # needs a full year of history
            px = r["AdjClose"]
            s200 = r.get("sma200")
            if not (ok(s200) and px > s200):
                continue                       # quality gate: above its own trend
            if self._tv_avg(code) < liq_floor:
                continue                       # liquidity gate, sized to my book
            atr = r.get("atr_pct")
            if ok(atr) and atr > MAX_ATR_PCT:
                continue                       # no volatility carnivals
            sc = (W_R12 * R12.get(code, 0.5)
                  + W_R6 * R6.get(code, 0.5)
                  + W_DY * (f_dy * RDY.get(code, 0.5) + (1.0 - f_dy) * 0.5)
                  + W_PERS * (f_pe * RPE.get(code, 0.5) + (1.0 - f_pe) * 0.5))
            if crowd:
                sc += min(PEER_TILT_CAP, PEER_TILT * crowd.get(code, 0.0))
            out.append((sc, code, r))
        out.sort(key=lambda t: (-t[0], t[1]))
        return out

    # ------------------------------------------------------------- exposure
    def _target_exposure(self, breadth, equity):
        """Graduated risk valve.

        Gross exposure is a continuous function of market breadth (the share
        of the universe holding its own 50-day mean) — it starts stepping down
        while participation is merely thinning, not after the damage is done.
        An own-drawdown circuit breaker sits on top of it.
        """
        e = 1.0
        if ok(breadth):
            span = max(1e-6, BREADTH_FULL - BREADTH_MIN)
            frac = (breadth - BREADTH_MIN) / span
            e = EXPO_MIN + (1.0 - EXPO_MIN) * max(0.0, min(1.0, frac))
        if self.peak_equity > 0 and equity / self.peak_equity - 1.0 < DD_TRIGGER:
            e = min(e, EXPO_DD)
        self.risk_off = e < 0.75
        return e

    # ------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx.get("names", {})
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        peers = ctx.get("peers", {}) or {}
        cash = float(portfolio.get("cash", 0.0))
        equity = max(float(portfolio.get("equity", 0.0)), 1.0)
        positions = portfolio.get("positions", {}) or {}
        prev_peak = self.peak_equity
        self.peak_equity = max(self.peak_equity, equity)

        self._update_state(view, day)

        # First session of a Tadawul week. The market trades Sun-Thu, so a
        # calendar gap of three days or more is the weekend (or a holiday
        # break) — weekday ordering alone would misread Sunday-started weeks.
        new_week = self.prev_date is None or (date - self.prev_date).days >= 3
        self.prev_date = date

        # dividends credited today (ex-date) — the compounding fuel
        div_today, div_payer, div_best = 0.0, None, 0.0  # ex-date cash, biggest payer
        for c, p in positions.items():
            r = view.get(c)
            if r is not None:
                d = r.get("Dividends")
                if ok(d) and d > 0:
                    amt = p["shares"] * d
                    div_today += amt
                    if amt > div_best:
                        div_best, div_payer = amt, c
        self.div_total += div_today

        was_off = self.risk_off
        target_e = self._target_exposure(breadth, equity)
        self.risk_off_days = self.risk_off_days + 1 if self.risk_off else 0
        invested = sum(p["weight"] for p in positions.values())

        sells, buys = [], []
        harvested, opened, added, trimmed, exited = [], [], [], [], []

        # ---------------------------------------------------- 1. harvest greed
        for c, p in positions.items():
            r = view.get(c)
            if r is None or day - self.harvest_lock.get(c, -999) < 21:
                continue
            rsi = r.get("rsi14")
            pb = r.get("bb_pctb")
            px = r.get("AdjClose")
            s200 = r.get("sma200")
            if (ok(rsi) and rsi > HARVEST_RSI and ok(pb) and pb > 1.0
                    and ok(px) and ok(s200) and s200 > 0 and px > HARVEST_EXT * s200
                    and p["value"] * HARVEST_CUT > MIN_SELL):
                sells.append({"code": c, "side": "sell", "fraction": HARVEST_CUT,
                              "reason": f"harvest: RSI {rsi:.0f}, {px / s200 - 1:+.0%} "
                                        f"over its 200-day mean"})
                self.harvest_lock[c] = day
                harvested.append((c, r))

        harvest_codes = {c for c, _ in harvested}

        # ---------------------------------------------------- 2. weekly accumulation
        if new_week:
            ranked = self._rank_candidates(view, day, equity, peers)
            self.last_rank = ranked
            picks = ranked[:N_SLOTS]
            per = min(MAX_W, target_e / max(1, len(picks))) if picks else 0.0
            tgt = {c: per for _, c, _ in picks}

            cur = {c: p["weight"] for c, p in positions.items()}
            for c in list(cur) + [c for c in tgt if c not in cur]:
                if c in harvest_codes:
                    continue
                cw = cur.get(c, 0.0)
                tw = tgt.get(c, 0.0)
                delta = tw - cw
                nw = cw + (A_UP if delta > 0 else A_DN) * delta
                if tw <= 0.0 and nw < DUST_W:
                    nw = 0.0
                move = (nw - cw) * equity
                if move < -MIN_SELL and cw > 0:
                    p = positions[c]
                    if nw <= 0.0:
                        sells.append({"code": c, "side": "sell", "all": True,
                                      "reason": "no longer earns its place in the core"})
                        exited.append(c)
                    else:
                        frac = min(0.95, max(0.0, -move / max(p["value"], 1.0)))
                        if frac > 0.05:
                            sells.append({"code": c, "side": "sell", "fraction": round(frac, 3),
                                          "reason": "scaling back toward target weight"})
                            trimmed.append(c)
                elif move > MIN_BUY:
                    r = view.get(c)
                    if r is not None and ok(r.get("AdjClose")):
                        buys.append([c, move, r])
                        (opened if c not in cur else added).append(c)

        # ---------------------------------------------------- 3. exposure valve
        else:
            held_n = max(1, len(positions))
            cap = MAX_W * held_n
            want = min(target_e, cap)
            if positions and invested > want + BAND:
                # de-risk across the whole core, pro rata: the valve controls how
                # much of the book is at risk, the ranking controls what is owned.
                cut = 1.0 - want / invested
                for c, p in positions.items():
                    if c in harvest_codes:
                        continue
                    if cut > 0.03 and p["value"] * cut > MIN_SELL:
                        sells.append({"code": c, "side": "sell", "fraction": round(min(0.95, cut), 3),
                                      "reason": f"risk-off: breadth {breadth:.0%} — gross exposure "
                                                f"down to {want:.0%}"})
                        trimmed.append(c)
            elif positions and invested < want - BAND and cash > MIN_BUY:
                f = want / max(invested, 1e-6)
                for c, p in positions.items():
                    r = view.get(c)
                    if r is None or not ok(r.get("AdjClose")):
                        continue
                    s200 = r.get("sma200")
                    if not (ok(s200) and r["AdjClose"] > s200):
                        continue
                    add = p["value"] * (f - 1.0)
                    if add > MIN_BUY and p["weight"] * f <= MAX_W:
                        buys.append([c, add, r])
                        added.append(c)

        # ---------------------------------------------------- 4. cash discipline
        est_proceeds = 0.0
        for od in sells:
            p = positions.get(od["code"])
            if not p:
                continue
            if od.get("all"):
                est_proceeds += p["value"]
            else:
                est_proceeds += p["value"] * float(od.get("fraction", 0.0))
        budget = cash + 0.97 * est_proceeds - 50.0
        want_total = sum(b[1] for b in buys)
        if want_total > budget and want_total > 0:
            scale = max(0.0, budget / want_total)
            for b in buys:
                b[1] *= scale
        orders = list(sells)   # sells first: the engine fills in order, funding the buys
        for c, sar, r in buys:
            if sar >= MIN_BUY:
                px = r.get("AdjClose", 0.0)
                d52 = r.get("dist_52w_high")
                tag = f"{d52:+.0%} from its 52w high" if ok(d52) else "trend intact"
                orders.append({"code": c, "side": "buy", "sar": round(sar, 2),
                               "reason": f"accumulating quality at {px:.2f} ({tag})"})

        # ---------------------------------------------------- 5. sentiment & voice
        s = 0.0
        if ok(breadth):
            s += 1.6 * (breadth - 0.42)
        trow = view.get("TASI")
        if trow is not None:
            tp, t200 = trow.get("AdjClose"), trow.get("sma200")
            if ok(tp) and ok(t200) and t200 > 0:
                s += 0.18 if tp > t200 else -0.18
        s += 2.5 * tret
        sentiment = max(-1.0, min(1.0, s))

        if self.risk_off:
            mood = "defensive"
        elif target_e < 1.0:
            mood = "cautious"
        elif opened or added:
            mood = "accumulating"
        elif harvested:
            mood = "harvesting"
        elif div_today > 0:
            mood = "compounding"
        else:
            mood = "patient"

        top_c, top_w, top_up = None, 0.0, 0.0
        for c, p in positions.items():
            if p["weight"] > top_w:
                top_c, top_w, top_up = c, p["weight"], p["unrealized_pct"]
        nm = lambda c: names.get(c, c)

        note = ""
        if harvested:
            c, r = harvested[0]
            note = (f"Harvested {HARVEST_CUT:.0%} of {nm(c)} at {r['AdjClose']:.2f} — "
                    f"RSI {r.get('rsi14', 0):.0f} and {r['AdjClose'] / r['sma200'] - 1:+.0%} "
                    f"above its own 200-day mean. The business did not change that fast; "
                    f"the price did. Cash back to the queue.")
        elif exited and opened:
            note = (f"Rotation week: released {nm(exited[0])} (below trend, out of the top "
                    f"{N_SLOTS}) and started {nm(opened[0])}. The core is a standard the "
                    f"holding has to keep meeting, not a shrine.")
        elif opened:
            c = opened[0]
            r = view.get(c) or {}
            extra = f" plus {len(opened) - 1} more" if len(opened) > 1 else ""
            note = (f"Opened {nm(c)} at {r.get('AdjClose', 0):.2f}{extra} — 12m "
                    f"{r.get('ret_12m', 0):+.0%}, 6m {r.get('ret_6m', 0):+.0%}, "
                    f"turnover {self._tv_avg(c) / 1e6:.1f}m SAR/day. Position built in "
                    f"slices, not lumps.")
        elif exited:
            note = (f"Closed {nm(exited[0])}. It lost the 200-day line and the top-"
                    f"{N_SLOTS} ranking in the same month; a compounder that stops "
                    f"compounding is just a story with my money in it.")
        elif trimmed and target_e < 1.0:
            note = (f"Breadth {breadth:.0%} — only that share of the market is above its "
                    f"50-day mean. Gross exposure down to {target_e:.0%} across "
                    f"{len(positions)} names. I would rather be early to cash than "
                    f"eloquent about a drawdown.")
        elif added and target_e >= 1.0:
            note = (f"Topped up {len(added)} core holdings back toward target; breadth "
                    f"{breadth:.0%} says the tape is carrying more names than it is "
                    f"dropping. Cash at {cash / equity:.0%} of the book and shrinking.")
        elif div_today > 0:
            note = (f"{nm(div_payer)} paid {div_today:,.0f} SAR today — {self.div_total:,.0f} "
                    f"SAR of dividends banked so far. That cash gets ranked like any other "
                    f"riyal at the next accumulation, not parked out of sentiment.")
        elif self.risk_off and not was_off:
            note = (f"Valve stepping down. Breadth {breadth:.0%} — that is participation "
                    f"failing, not a rotation. Gross target cut to {target_e:.0%} across "
                    f"{len(positions)} names. The rule moves before my opinion does.")
        elif was_off and not self.risk_off:
            note = (f"Valve reopening after {self.risk_off_days} sessions of reduced gross: "
                    f"breadth back to {breadth:.0%}, target {target_e:.0%}. Rebuilding in "
                    f"weekly slices from the top of the ranking.")
        elif self.risk_off:
            note = (f"Risk-off holds at {invested:.0%} invested against a {target_e:.0%} target; "
                    f"breadth {breadth:.0%}, TASI {tret:+.1%} today. Capital that survives a bad "
                    f"tape is the only capital that compounds through one.")
        elif equity < prev_peak * (1.0 + DD_TRIGGER):
            note = (f"Book is {equity / max(prev_peak, 1.0) - 1:+.1%} off its high-water mark, "
                    f"past my {abs(DD_TRIGGER):.0%} line — gross capped at {EXPO_DD:.0%} until it "
                    f"heals. Drawdown arithmetic is unforgiving; I would rather do the boring "
                    f"repair now.")
        else:
            quiet = [
                (f"{len(positions)} compounders, {invested:.0%} invested, cash "
                 f"{cash:,.0f} SAR. Largest is {nm(top_c)} at {top_w:.0%} of the book, "
                 f"{top_up:+.0%} on cost.") if top_c else
                (f"No position clears the gate today: cash {cash:,.0f} SAR is a "
                 f"position too."),
                (f"Dividends banked to date {self.div_total:,.0f} SAR. Breadth {breadth:.0%}, "
                 f"exposure target {target_e:.0%}. Nothing to do is a decision I am paid "
                 f"to make correctly."),
                (f"Ranking table steady — {len(self.last_rank)} names clear the quality, "
                 f"liquidity and trend gates. Holding {len(positions)}; the other "
                 f"{max(0, len(self.last_rank) - len(positions))} can wait their turn."),
                (f"Equity {equity:,.0f} SAR at a fresh high-water mark; breadth "
                 f"{breadth:.0%} and the valve wide open. Compounding is mostly the "
                 f"absence of unforced errors.")
                if equity >= prev_peak else
                (f"Equity {equity:,.0f} SAR, {equity / max(prev_peak, 1.0) - 1:+.1%} below the "
                 f"high-water mark. Breadth {breadth:.0%}, exposure {invested:.0%}. Nothing "
                 f"here has broken a rule, so nothing here gets sold on feeling."),
            ]
            if peers:
                lead = max(peers.items(), key=lambda kv: kv[1].get("ret_63", 0.0) or 0.0)
                quiet.append(
                    f"{lead[0]} leads the 63-day tables at "
                    f"{(lead[1].get('ret_63') or 0.0):+.1%} with "
                    f"{(lead[1].get('cash_frac') or 0.0):.0%} in cash. Noted, not copied — "
                    f"their positioning only breaks ties on my own ranking.")
            note = quiet[day % len(quiet)]

        return {"orders": orders, "sentiment": round(sentiment, 3),
                "mood": mood, "note": note}


STRATEGY = Hikma()
