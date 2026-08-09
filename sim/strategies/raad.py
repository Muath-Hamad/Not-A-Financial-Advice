"""Raad (رعد, "thunder") — small/mid-cap breakout desk.

Thesis: on Tadawul the index is a decoy. Over 2022-2026 the average liquid name
bled ~-1.5% per quarter, but names printing fresh 52-week highs in the *mid*
liquidity band earned a large positive spread over that base. The whole edge is
(a) fishing only in that band, (b) waiting for the high to actually print, and
(c) exit asymmetry — small stops, wide trails, so 50%-ish hit rate compounds.

THE RULEBOOK
------------
1. UNIVERSE (screen, re-derived every session, never a fixed list)
   - Trailing turnover EMA in [8M, 70M] SAR. The floor kills the illiquid tail
     (breakouts there are a trap: forward returns are negative). The ceiling
     kills the mega-caps, which are index proxies, not breakout vehicles.
   - Today's turnover >= 1.5M SAR, price >= 2.00 SAR, ATR% in [1.5%, 7.0%].
2. TRIGGER (all must hold, no exceptions)
   - Close within 2% of the 52-week high  -> the base has actually resolved.
   - Close above sma50, 3-month return >= 0  -> not a dead-cat print.
3. RANK (selectivity, not signal count): a composite of proximity to the 52w
   high, 3m/6m thrust, relative strength vs TASI, and today's volume vs its
   20-day average (volume confirms, it does not veto). Max 2 new names/session.
4. REGIME GATE — no new risk unless TASI > its own sma50 AND market breadth
   >= 44% of names above their sma50, and never the day after TASI drops 2.5%.
   Breakouts bought into a broken tape are the single most expensive habit in
   this school.
5. SIZE by volatility, not conviction: weight = 2.2% equity risk / (2.4 x ATR%),
   clamped to [6%, 25%], gross book capped at 95%. Small ATR -> bigger line.
6. EXITS (asymmetric, mechanical)
   - initial stop: entry - 2.4 x ATR(at entry); backstop hard stop at -12%
   - trail: peak-since-entry - 5.0 x ATR, armed once +10% (wide on purpose —
     a 3-ATR trail cut the compounders in half)
   - time stop: 25 sessions without +2% is dead money, recycle it
   - profit book: sell 45% of the line at +45% and let the rest ride
7. CIRCUIT BREAKERS — half size below -13% own drawdown; flat and stand down
   10 sessions below -15%; no new entries for 5 sessions after any -4% day.
8. PEERS (when the arena is populated) tilt the RANKING only: names held by the
   top third of peers by 63-day return score higher, names a leader dumped today
   score lower. Peers never open a trade my own gates rejected — standalone
   behaviour is the floor, peers are the bonus.

No dates, no per-ticker plans, no memorised tape. Deterministic, stdlib only.
"""

from __future__ import annotations

import random

from strategy_base import Strategy

# --- universe screen -------------------------------------------------------
LIQ_LO = 8_000_000.0      # trailing turnover floor (SAR) — liquidity discipline
LIQ_HI = 70_000_000.0     # ceiling — above this we are trading the index, not a breakout
TURN_TODAY_MIN = 1_500_000.0
PX_MIN = 2.0
ATR_LO, ATR_HI = 0.015, 0.070
TURN_ALPHA = 0.05         # EMA weight on today's turnover

# --- breakout trigger ------------------------------------------------------
D52_MAX = -0.02           # must close within 2% of the 52-week high
RET3M_MIN = 0.0

# --- portfolio -------------------------------------------------------------
MAX_POS = 6
RISK_PER_TRADE = 0.022
STOP_ATR = 2.4
W_MIN, W_MAX = 0.06, 0.25
MAX_GROSS = 0.95
MIN_BUY = 3_500.0
ENTRIES_PER_DAY = 2
REENTRY_COOL = 8
ORDER_GUARD = 4           # sessions before re-queuing the same code

# --- exits -----------------------------------------------------------------
HARD_STOP = -0.12
TRAIL_ATR = 5.0
TRAIL_ARM = 0.10
TIME_STOP = 25
TIME_MIN = 0.02
PARTIAL_AT = 0.45
PARTIAL_FRAC = 0.45

# --- risk switches ---------------------------------------------------------
DD_TRIM = 0.13
DD_FLAT = 0.15
FLAT_DAYS = 10
DAYLOSS = -0.04
DAYLOSS_COOL = 5
BREADTH_MIN = 0.44
TASI_CRASH = -0.025

PEER_BONUS_CAP = 0.25
PEER_DUMP_PENALTY = 0.40

MOODS_HUNT = ["locked on", "coiled", "patient", "scanning", "on the bid"]
MOODS_LONG = ["riding it", "letting it work", "in the trend", "paid", "position on"]
MOODS_CUT = ["clipped", "stopped", "unsentimental", "flat and fine", "reset"]
MOODS_OFF = ["hands off", "cash is a position", "standing down", "no tape, no trade"]


class Raad(Strategy):
    meta = {
        "handle": "raad",
        "name": "Raad",
        "emoji": "⚡",
        "tagline": "I don't predict the storm. I trade the strike.",
        "character": (
            "A systematic small/mid-cap breakout trader who treats every entry as a "
            "hypothesis with a pre-written funeral: fixed risk in, ATR trail out, no "
            "arguing with the tape. Competitive to the bone and quietly smug about "
            "the trades he does not take."
        ),
        "risk_style": "selective small/mid-cap breakout momentum",
        "color": "#888888",
    }

    def __init__(self):
        self._rng = random.Random(20260802)   # phrasing only; never touches orders
        self._turn = {}          # code -> EMA of turnover_sar
        self._peak = {}          # code -> highest close seen since entry
        self._atr0 = {}          # code -> ATR at entry (stop reference)
        self._entry_day = {}     # code -> sim day the buy was queued
        self._cool = {}          # code -> day until which re-entry is barred
        self._ordered = {}       # code -> day an order was queued (dupe guard)
        self._partial = set()    # codes already scaled once
        self._eq_peak = 0.0
        self._no_buy_until = -1
        self._flat_mode = False
        self._flat_until = -1
        self._sent_prev = 0.0
        self._n_wins = 0
        self._n_losses = 0

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _ok(x):
        return isinstance(x, (int, float)) and x == x and abs(x) != float("inf")

    def _peer_read(self, ctx):
        """Leaders' book + today's leader dumps. Empty dicts when running solo."""
        peers = ctx.get("peers") or {}
        lead_w, dumped, best = {}, set(), None
        if not peers:
            return lead_w, dumped, best, 0.0
        rows = []
        for h, v in peers.items():
            if isinstance(v, dict):
                r63 = v.get("ret_63")
                rows.append((r63 if self._ok(r63) else 0.0, h, v))
        if not rows:
            return lead_w, dumped, best, 0.0
        rows.sort(key=lambda t: -t[0])
        best = rows[0][1]
        n_lead = max(1, len(rows) // 3)
        for r63, h, v in rows[:n_lead]:
            if r63 <= 0:
                continue
            for code, w in (v.get("positions") or {}).items():
                if self._ok(w):
                    lead_w[code] = lead_w.get(code, 0.0) + float(w)
            for t in (v.get("today_trades") or []):
                if isinstance(t, dict) and t.get("side") == "sell":
                    dumped.add(str(t.get("code", "")))
        r21 = [v.get("ret_21") for _, _, v in rows if self._ok(v.get("ret_21"))]
        peer_tone = (sum(r21) / len(r21)) if r21 else 0.0
        return lead_w, dumped, best, peer_tone

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0))
        names = ctx.get("names") or {}
        pos = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        eq = float(portfolio.get("equity", 0.0) or 0.0) or 1.0
        hist = ctx.get("equity_history") or [eq]
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = breadth if self._ok(breadth) else 0.5
        tret = ctx.get("tasi_ret_1d", 0.0)
        tret = tret if self._ok(tret) else 0.0

        self._eq_peak = max(self._eq_peak, eq)
        dd = (eq / self._eq_peak - 1.0) if self._eq_peak > 0 else 0.0
        own_1d = (hist[-1] / hist[-2] - 1.0) if len(hist) >= 2 and hist[-2] else 0.0

        # --- trailing liquidity state (causal EMA of turnover)
        for c, r in view.items():
            if c == "TASI" or c == "TASI_SR":
                continue
            t = r.get("turnover_sar")
            if self._ok(t) and t >= 0.0:
                prev = self._turn.get(c)
                self._turn[c] = t if prev is None else prev * (1 - TURN_ALPHA) + t * TURN_ALPHA

        # --- regime read
        tasi = view.get("TASI") or view.get("TASI_SR") or {}
        tc, ts50 = tasi.get("AdjClose"), tasi.get("sma50")
        reg50 = self._ok(tc) and self._ok(ts50) and tc > ts50
        ts200 = tasi.get("sma200")
        reg200 = self._ok(tc) and self._ok(ts200) and tc > ts200

        lead_w, lead_dumped, best_peer, peer_tone = self._peer_read(ctx)

        orders, events, sold = [], [], set()

        # ------------------------------------------------------- exits first
        for c, ph in pos.items():
            r = view.get(c)
            px = r.get("Close") if r is not None else None
            up = ph.get("unrealized_pct", 0.0)
            up = up if self._ok(up) else 0.0
            if self._ok(px):
                self._peak[c] = max(self._peak.get(c, px), px)
            pk = self._peak.get(c)
            a0 = self._atr0.get(c)
            atr = r.get("atr14") if r is not None else None
            held = day - self._entry_day.get(c, day)
            cost = ph.get("avg_cost")
            reason = None

            if a0 and self._ok(px) and self._ok(cost) and cost > 0:
                if px <= cost - STOP_ATR * a0:
                    reason = f"stop: {px:.2f} through {cost - STOP_ATR * a0:.2f} (2.4 ATR under cost)"
            if reason is None and up <= HARD_STOP:
                reason = f"hard stop at {up:+.1%} — the thesis was wrong, not early"
            if reason is None and pk and self._ok(px) and self._ok(atr) and up >= TRAIL_ARM:
                if px <= pk - TRAIL_ATR * atr:
                    reason = (f"trail hit: {px:.2f} vs peak {pk:.2f} less 5 ATR "
                              f"({atr:.2f}); banked {up:+.1%}")
            if reason is None and held >= TIME_STOP and up < TIME_MIN:
                reason = f"time stop: {held} sessions for {up:+.1%} — capital has a better job"
            if reason is None and self._flat_mode:
                reason = f"circuit breaker: book {dd:+.1%} off its high, everything to cash"

            if reason:
                orders.append({"code": c, "side": "sell", "all": True, "reason": reason})
                sold.add(c)
                self._cool[c] = day + REENTRY_COOL
                if up >= 0:
                    self._n_wins += 1
                    events.append(("win", c, up, reason))
                else:
                    self._n_losses += 1
                    events.append(("loss", c, up, reason))
                continue

            if up >= PARTIAL_AT and c not in self._partial:
                orders.append({"code": c, "side": "sell", "fraction": PARTIAL_FRAC,
                               "reason": f"scale out {PARTIAL_FRAC:.0%} at {up:+.1%} — "
                                         f"pay the desk, let the rest run"})
                self._partial.add(c)
                events.append(("scale", c, up, None))

        for c in list(self._peak):
            if c not in pos:
                self._peak.pop(c, None)
                self._atr0.pop(c, None)
                self._entry_day.pop(c, None)
                self._partial.discard(c)

        # ---------------------------------------------------- risk switches
        if not self._flat_mode and dd <= -DD_FLAT:
            self._flat_mode = True
            self._flat_until = day + FLAT_DAYS
            self._eq_peak = eq            # reset the reference once the bleed is stopped
            events.append(("flat", None, dd, None))
        elif self._flat_mode and day > self._flat_until and reg50:
            self._flat_mode = False
            self._eq_peak = eq
            events.append(("resume", None, dd, None))
        if own_1d <= DAYLOSS:
            self._no_buy_until = max(self._no_buy_until, day + DAYLOSS_COOL)

        n_open = len([c for c in pos if c not in sold])
        n_pend = len([c for c, d0 in self._ordered.items()
                      if c not in pos and day - d0 <= ORDER_GUARD])
        slots = MAX_POS - n_open - n_pend
        gross = sum(ph.get("value", 0.0) for c, ph in pos.items() if c not in sold) / eq

        gate_ok = reg50 and breadth >= BREADTH_MIN and tret > TASI_CRASH
        can_buy = (gate_ok and not self._flat_mode and day > self._no_buy_until
                   and slots > 0 and cash >= MIN_BUY and gross < MAX_GROSS)
        risk_mult = 0.5 if dd <= -DD_TRIM else 1.0

        # -------------------------------------------------- screen and rank
        cands = []
        scanned = 0
        if can_buy:
            for c, r in view.items():
                if c in ("TASI", "TASI_SR") or c in pos or c in sold:
                    continue
                if day <= self._cool.get(c, -1):
                    continue
                if day - self._ordered.get(c, -999) <= ORDER_GUARD:
                    continue
                px = r.get("Close")
                if not self._ok(px) or px < PX_MIN:
                    continue
                tt = self._turn.get(c)
                if tt is None or tt < LIQ_LO or tt > LIQ_HI:
                    continue
                t_today = r.get("turnover_sar")
                if not self._ok(t_today) or t_today < TURN_TODAY_MIN:
                    continue
                d52 = r.get("dist_52w_high")
                if not self._ok(d52) or d52 < D52_MAX:
                    continue
                apct = r.get("atr_pct")
                if not self._ok(apct) or apct < ATR_LO or apct > ATR_HI:
                    continue
                s50 = r.get("sma50")
                if not (self._ok(s50) and px > s50):
                    continue
                r3 = r.get("ret_3m")
                if not self._ok(r3) or r3 < RET3M_MIN:
                    continue
                scanned += 1
                r6 = r.get("ret_6m")
                r6 = r6 if self._ok(r6) else 0.0
                vs, vv = r.get("vol_sma20"), r.get("Volume")
                vr = (vv / vs) if (self._ok(vs) and vs > 0 and self._ok(vv)) else 1.0
                rs = r.get("rs_tasi_3m")

                sc = 6.0 * max(0.0, d52 + 0.05)
                sc += 1.0 * min(1.0, max(0.0, r3))
                sc += 0.8 * min(1.0, max(0.0, r6))
                sc += 0.25 * min(2.0, vr)
                if self._ok(rs):
                    sc += 0.5 * min(1.0, max(-0.5, rs))
                # peers tilt the ranking only — never a gate
                lw = lead_w.get(c)
                if lw:
                    sc += min(PEER_BONUS_CAP, 0.6 * lw)
                if c in lead_dumped:
                    sc -= PEER_DUMP_PENALTY
                cands.append((sc, c, r, apct, d52, vr))
            cands.sort(key=lambda t: (-t[0], t[1]))

        # ------------------------------------------------------- entries
        bought = 0
        avail = min(cash, max(0.0, MAX_GROSS - gross) * eq)
        for sc, c, r, apct, d52, vr in cands:
            if bought >= ENTRIES_PER_DAY or slots <= 0:
                break
            stop_d = max(0.04, STOP_ATR * apct)
            w = max(W_MIN, min(W_MAX, RISK_PER_TRADE * risk_mult / stop_d))
            sar = min(w * eq, avail)
            if sar < MIN_BUY:
                break
            nm = names.get(c, c)
            reason = (f"{nm}: {abs(d52):.1%} off the 52w high, vol {vr:.1f}x its 20d, "
                      f"ATR {apct:.1%} -> {w:.0%} line, stop {stop_d:.1%} out")
            orders.append({"code": c, "side": "buy", "sar": round(sar, 2), "reason": reason})
            self._ordered[c] = day
            self._entry_day[c] = day + 1
            a = r.get("atr14")
            self._atr0[c] = a if self._ok(a) else None
            px = r.get("Close")
            self._peak[c] = px if self._ok(px) else 0.0
            avail -= sar
            bought += 1
            slots -= 1
            events.append(("buy", c, sc, (d52, vr, w)))

        # ------------------------------------------------------ sentiment
        sent = 0.0
        sent += 0.9 * (breadth - 0.5)
        sent += 0.35 if reg50 else -0.35
        sent += 0.15 if reg200 else -0.10
        sent += 6.0 * own_1d
        sent += 0.20 * min(1.0, len(cands) / 6.0)
        if peer_tone:
            sent += 0.4 * max(-0.5, min(0.5, peer_tone))
        if any(e[0] == "loss" for e in events):
            sent -= 0.30
        if any(e[0] in ("win", "scale") for e in events):
            sent += 0.20
        if self._flat_mode:
            sent = min(sent, -0.55)
        sent = 0.45 * self._sent_prev + 0.55 * sent
        sent = max(-1.0, min(1.0, sent))
        self._sent_prev = sent

        if self._flat_mode or not gate_ok:
            mood = MOODS_OFF[day % len(MOODS_OFF)]
        elif any(e[0] == "loss" for e in events):
            mood = MOODS_CUT[day % len(MOODS_CUT)]
        elif n_open > 0:
            mood = MOODS_LONG[day % len(MOODS_LONG)]
        else:
            mood = MOODS_HUNT[day % len(MOODS_HUNT)]

        note = self._note(day, events, names, view, pos, sold, cands, scanned,
                          eq, cash, gross, breadth, reg50, reg200, tret, dd,
                          n_open, best_peer, lead_w)

        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}

    # ---------------------------------------------------------- journal
    def _note(self, day, events, names, view, pos, sold, cands, scanned,
              eq, cash, gross, breadth, reg50, reg200, tret, dd,
              n_open, best_peer, lead_w):
        pick = self._rng.randrange(3)
        inv = f"{gross:.0%} invested, SAR {cash:,.0f} dry"

        for kind, c, val, extra in events:
            nm = names.get(c, c) if c else ""
            if kind == "flat":
                return (f"Circuit breaker. Book is {val:+.1%} from its high, so the whole "
                        f"thing goes to cash at tomorrow's open and I sit on my hands for "
                        f"{FLAT_DAYS} sessions. Rule exists precisely so I don't get a vote today.")
            if kind == "buy":
                d52, vr, w = extra
                variants = [
                    f"Strike: {nm}. Closed {abs(d52):.1%} under its 52-week high on "
                    f"{vr:.1f}x average volume, breadth {breadth:.0%}, TASI over its 50-day. "
                    f"Sized to {w:.0%} on ATR, stop pre-committed. {scanned} names passed the "
                    f"screen today; I took {min(ENTRIES_PER_DAY, len([e for e in events if e[0]=='buy']))}.",
                    f"Adding {nm} at the open — the base resolved rather than the story being "
                    f"good. Score {val:.2f}, volume {vr:.1f}x its 20-day. {w:.0%} of book, "
                    f"nothing more. {inv} before the fill.",
                    f"{nm} is the cleanest print on the board: {abs(d52):.1%} off the high with "
                    f"real turnover behind it. {w:.0%} line, ATR-scaled. I'd rather own two "
                    f"honest breakouts than six opinions.",
                ]
                return variants[pick]
            if kind == "scale":
                return (f"Booked {PARTIAL_FRAC:.0%} of {nm} at {val:+.1%}. The rest keeps its "
                        f"5-ATR trail. Taking the whole thing here is how you turn a "
                        f"three-bagger into a nice lunch. {inv}.")
            if kind == "loss":
                return (f"Out of {nm} at {val:+.1%} — {extra}. That is the cost of doing "
                        f"business in this school; I've paid it {self._n_losses} times for "
                        f"{self._n_wins} winners. Book SAR {eq:,.0f}.")
            if kind == "win":
                return (f"Closed {nm} {val:+.1%}. {extra}. Winners get a wide leash and losers "
                        f"get a short one — that asymmetry is the entire strategy, not the "
                        f"entries. Equity SAR {eq:,.0f}, {inv}.")
            if kind == "resume":
                return (f"Stand-down over. TASI back above its 50-day, breadth {breadth:.0%}, "
                        f"drawdown reference reset. Re-arming the screen tomorrow with "
                        f"SAR {cash:,.0f} of dry powder.")

        if self._flat_mode:
            return (f"Still flat by rule — {max(0, self._flat_until - day)} sessions of the "
                    f"stand-down left. TASI {tret:+.2%} today, breadth {breadth:.0%}. "
                    f"Cash pays nothing and loses nothing; I'll take the second half of that.")
        if not reg50 or breadth < BREADTH_MIN:
            why = ("TASI is under its own 50-day" if not reg50
                   else f"breadth {breadth:.1%} sits under my {BREADTH_MIN:.0%} floor")
            variants = [
                f"No new risk — {why}. Breakouts bought into a broken tape are the most "
                f"expensive habit in this business. Holding {n_open} names, {inv}.",
                f"Screen is switched off: {why}, index {tret:+.2%} today. I can see setups; "
                f"I'm not paid to see them, I'm paid to see them work. SAR {cash:,.0f} waiting.",
                f"Tape fails the regime test again — {why}. {n_open} positions left running "
                f"on their trails, no additions. Patience is a position size.",
            ]
            return variants[pick]

        if cands:
            sc, c, r, apct, d52, vr = cands[0]
            nm = names.get(c, c)
            tail = ""
            if best_peer and lead_w:
                tail = f" Leaderboard's book overlaps {len(lead_w)} of my screen; noted, not obeyed."
            variants = [
                f"{scanned} names cleared the screen, best is {nm} (score {sc:.2f}, "
                f"{abs(d52):.1%} off its high, {vr:.1f}x volume). No slot or no cash today, so "
                f"it stays on the sheet. {inv}, breadth {breadth:.0%}.{tail}",
                f"Watchlist: {nm} leading at {sc:.2f}. Regime is clean (TASI above the 50-day"
                f"{', above the 200-day' if reg200 else ''}, breadth {breadth:.0%}) but the book "
                f"is already {gross:.0%} committed across {n_open} names.{tail}",
                f"Holding {n_open}, {inv}. {nm} is the sharpest setup on the board but "
                f"discipline says two entries a session, maximum. Equity SAR {eq:,.0f}, "
                f"{dd:+.1%} from the high water mark.{tail}",
            ]
            return variants[pick]

        variants = [
            f"Nothing within 2% of a 52-week high in the 8-70M turnover band today. "
            f"Breadth {breadth:.0%}, TASI {tret:+.2%}. {n_open} positions on trails, "
            f"{inv}. A quiet screen is information, not a problem.",
            f"Zero qualifying breakouts. The mid-cap band is chopping, not resolving. "
            f"Book SAR {eq:,.0f}, {dd:+.1%} off the high, nothing forced.",
            f"Screen empty again — plenty of names moving, none of them printing new highs "
            f"on volume in my liquidity band. Sitting with {inv} and no regrets.",
        ]
        return variants[pick]


STRATEGY = Raad()
