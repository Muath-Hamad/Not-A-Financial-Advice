"""Abu Shanab — old-school Souq veteran, trading Tadawul since before the 2006 crash.

Trend is the only master. Weekly review on the first session of the week:
  - Regime: TASI above its own sma200 = safe to sail. Below = 2006 all over again.
  - Momentum book: 12-month-minus-1-month momentum, only names in full trend
    alignment (AdjClose > sma50 > sma200) with real turnover. Top 5 slots,
    equal weight; if breadth < 45% he sails at half mast (3 slots).
  - Cut losers without mercy: daily -10% stop from cost; weekly cut of any
    name that closes under its sma50 or whose momentum fades negative.
  - Aramco (2222) is family: a 10% anchor outside the ranking, stop at -18%,
    only abandoned if it sinks 5% below its own sma200.
  - Ramadan: no new positions. The souq sleeps, and so does his wallet.
  - Bunker rule (the 2006 scar): if his own equity draws down 12%, everything
    but a healthy Aramco goes to cash until TASI reclaims sma200 with breadth.
  - Never buy on a day TASI fell 2%+ — "don't catch a falling sword".
"""

from __future__ import annotations

import math

from strategy_base import Strategy

ARAMCO = "2222"

# Approximate Gregorian windows of Ramadan (superstition, not astronomy).
RAMADAN = [
    ("2022-04-02", "2022-05-01"),
    ("2023-03-23", "2023-04-20"),
    ("2024-03-11", "2024-04-09"),
    ("2025-03-01", "2025-03-29"),
    ("2026-02-18", "2026-03-19"),
]

PROVERBS = [
    "Al-souq ma yerham — the market shows no mercy, so neither do I.",
    "Ily fat mat: what has passed is dead. I trade the trend in front of me.",
    "A camel does not see its own hump — that's why I keep my stop-loss.",
    "Patience is the key to relief, but a stop-loss is the key to old age.",
    "The wind does not blow as the ships wish — so I sail with it, not against.",
    "He who watched 2006 from the trading floor needs no second lesson.",
    "Money is a coward: it runs from noise and hides with the trend.",
    "Al-tikrar yialem al-humar — even a donkey learns from repetition. I learned in 2006.",
    "Better a bird in the hand than ten on the tape.",
    "The dogs bark and the caravan moves on — my caravan is the 200-day line.",
    "Whoever digs a pit for the index falls into his own margin call.",
    "Trust in Allah, but tie your camel — and set your stop.",
]

MOODS_ON = ["gruff but content", "riding the caravan", "watchful", "old bones, warm tea", "stubborn as ever"]
MOODS_OFF = ["smelling 2006", "arms crossed", "counting cash beads", "cold-eyed", "bitter coffee"]


class AbuShanab(Strategy):
    meta = {
        "handle": "abu_shanab",
        "name": "Abu Shanab",
        "emoji": "🥸",
        "tagline": "The trend is my caravan; everything else is noise in the souq.",
        "character": (
            "A 58-year-old Souq veteran who has traded Tadawul since before the 2006 "
            "crash wiped out half his majlis. Trusts nothing but moving averages and "
            "12-month momentum, cuts losers without mercy, refuses to buy in Ramadan, "
            "and is secretly soft-hearted about Aramco."
        ),
        "risk_style": "disciplined trend-follower",
        "color": "#9D755D",
    }

    def __init__(self):
        self._prev_date = None
        self._risk_on = True
        self._bunker = False
        self._bunker_exit_day = -99
        self._peak_ref = 100_000.0
        self._last_shout = -99
        self._last_brag = -99
        self._pcount = 0
        self._was_ramadan = False

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _ok(x):
        return x is not None and isinstance(x, (int, float)) and x == x

    def _new_week(self, date):
        p = self._prev_date
        if p is None:
            return True
        return date.weekday() < p.weekday() or (date - p).days > 2

    @staticmethod
    def _iso(date):
        return f"{date.year:04d}-{date.month:02d}-{date.day:02d}"

    def _ramadan(self, iso):
        return any(a <= iso <= b for a, b in RAMADAN)

    def _proverb(self):
        self._pcount += 1
        return PROVERBS[self._pcount % len(PROVERBS)]

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        iso = self._iso(date)
        day = ctx["day_index"]
        names = ctx["names"]
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        new_week = self._new_week(date)
        self._prev_date = date
        ramadan = self._ramadan(iso)
        ramadan_starts = ramadan and not self._was_ramadan
        self._was_ramadan = ramadan

        positions = portfolio.get("positions", {})
        equity = portfolio.get("equity", 0.0)
        cash = portfolio.get("cash", 0.0)
        hist = ctx.get("equity_history") or [equity]
        peak = max(hist) if hist else equity
        # Drawdown measured from a peak reference that resets when he leaves
        # the bunker — the scar heals, the vigilance stays.
        self._peak_ref = max(self._peak_ref, equity)
        my_dd = (equity / self._peak_ref - 1.0) if self._peak_ref > 0 else 0.0

        # --- regime from the index ---
        tasi = view.get("TASI") or view.get("TASI_SR")
        tasi_fresh = True  # index also above its own sma50 = wind at our back
        if tasi is not None:
            ta, ts200 = tasi.get("AdjClose"), tasi.get("sma200")
            if self._ok(ta) and self._ok(ts200):
                self._risk_on = ta > ts200
            ts50 = tasi.get("sma50")
            if self._ok(ta) and self._ok(ts50):
                tasi_fresh = ta > ts50
        risk_on = self._risk_on
        prev_risk = getattr(self, "_prev_risk", risk_on)
        regime_flip = new_week and (risk_on != prev_risk)
        if new_week:
            self._prev_risk = risk_on

        # --- momentum ranking (12m minus 1m), trend-aligned, liquid ---
        ranked = []
        for c, r in view.items():
            if c in ("TASI", "TASI_SR") or c == ARAMCO:
                continue
            adj, s50, s200 = r.get("AdjClose"), r.get("sma50"), r.get("sma200")
            r12, r1, to = r.get("ret_12m"), r.get("ret_1m"), r.get("turnover_sar")
            if not all(self._ok(x) for x in (adj, s50, s200, r12, r1)):
                continue
            if not (adj > s50 > s200):
                continue
            mom = r12 - r1
            if mom <= 0:
                continue
            rs = r.get("rs_tasi_3m")
            if not self._ok(rs) or rs <= 0:
                continue  # must be beating the souq itself, not just drifting
            if not self._ok(to) or to < 2_000_000:
                continue
            ranked.append((mom, c))
        ranked.sort(reverse=True)
        rank_codes = [c for _, c in ranked]
        mom_of = {c: m for m, c in ranked}

        orders = []
        sold = set()
        events = []

        # --- bunker logic: the 2006 scar ---
        if (not self._bunker and my_dd <= -0.12
                and day - self._bunker_exit_day >= 10):
            self._bunker = True
            events.append("bunker_in")
        elif self._bunker and new_week and risk_on and breadth >= 0.50:
            self._bunker = False
            self._bunker_exit_day = day
            self._peak_ref = equity  # the scar heals: measure pain from here
            events.append("bunker_out")

        # --- daily merciless stop from cost ---
        for c, p in positions.items():
            if c in sold:
                continue
            upnl = p.get("unrealized_pct", 0.0)
            limit = -0.18 if c == ARAMCO else -0.10
            if self._ok(upnl) and upnl <= limit:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"stop {upnl:+.1%}: I cut losers, they don't cut me"})
                sold.add(c)
                events.append(("stop", c, upnl))

        # --- bunker liquidation ---
        if self._bunker:
            for c, p in positions.items():
                if c in sold:
                    continue
                if c == ARAMCO:
                    r = view.get(c)
                    if r and self._ok(r.get("AdjClose")) and self._ok(r.get("sma200")) \
                            and r["AdjClose"] > r["sma200"]:
                        continue  # the old man keeps his Aramco if it still stands tall
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": "bunker: I saw 2006, I will not see it twice"})
                sold.add(c)

        # --- weekly trend review ---
        if new_week and not self._bunker:
            for c, p in positions.items():
                if c in sold:
                    continue
                r = view.get(c)
                if r is None:
                    continue  # halted: nothing to judge today
                adj, s50 = r.get("AdjClose"), r.get("sma50")
                if c == ARAMCO:
                    s200 = r.get("sma200")
                    if self._ok(adj) and self._ok(s200) and adj < s200 * 0.95:
                        orders.append({"code": c, "side": "sell", "all": True,
                                       "reason": "even Aramco... below the 200-line. Forgive me."})
                        sold.add(c)
                        events.append(("aramco_sold", adj))
                    continue
                # A held camel gets a little rope: 1.5% under sma50 before the
                # knife, and momentum must turn clearly negative, not just cool.
                broke = self._ok(adj) and self._ok(s50) and adj < s50 * 0.985
                r12, r1 = r.get("ret_12m"), r.get("ret_1m")
                faded = (self._ok(r12) and self._ok(r1) and (r12 - r1) < -0.05)
                if broke or faded:
                    why = "closed under sma50" if broke else "momentum faded"
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"{why} — the caravan leaves it behind"})
                    sold.add(c)
                    events.append(("cut", c))

            # --- weekly buys ---
            can_buy = (risk_on and tasi_fresh and not ramadan
                       and tret > -0.02 and cash > 2000)
            if can_buy:
                n_slots = 5 if breadth >= 0.45 else 3
                slot_w = 0.165
                held_mom = [c for c in positions
                            if c != ARAMCO and c not in sold]
                free = n_slots - len(held_mom)
                bought = []
                for c in rank_codes:
                    if free <= 0:
                        break
                    if c in positions or c in sold:
                        continue
                    orders.append({"code": c, "side": "buy", "weight": slot_w,
                                   "reason": f"12m-1m mom {mom_of[c]:+.0%}, riding above sma50>sma200"})
                    bought.append(c)
                    free -= 1
                if bought:
                    events.append(("bought", bought))
                # Aramco anchor: the soft spot
                ra = view.get(ARAMCO)
                if ra is not None and ARAMCO not in sold:
                    aw = positions.get(ARAMCO, {}).get("weight", 0.0)
                    adj, s200 = ra.get("AdjClose"), ra.get("sma200")
                    if self._ok(adj) and self._ok(s200) and adj > s200 and aw < 0.06:
                        orders.append({"code": ARAMCO, "side": "buy", "weight": 0.10 - aw,
                                       "reason": "the anchor: a house is not a home without Aramco"})
                        events.append(("anchor", adj))

        # ------------------------------------------------------ sentiment
        sent = (0.45 if risk_on else -0.45) + (breadth - 0.5) * 0.6
        sent += max(-0.25, min(0.25, tret * 8))
        if self._bunker:
            sent = min(sent, -0.5)
        sent = max(-1.0, min(1.0, sent))

        mood = (MOODS_OFF if (self._bunker or not risk_on) else MOODS_ON)[day % 5]
        if ramadan:
            mood = "fasting from the tape"

        # ----------------------------------------------------------- note
        n_pos = len([c for c in positions if c not in sold])
        tlevel = tasi.get("AdjClose") if tasi is not None else float("nan")
        note = self._make_note(day, iso, risk_on, breadth, tret, tlevel, n_pos,
                               ramadan, events, rank_codes, view, names, my_dd, equity)

        # ---------------------------------------------------------- shout
        shout = self._make_shout(day, iso, risk_on, regime_flip, ramadan_starts,
                                 tret, events, names, ctx, equity, peak, breadth)

        out = {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}
        if shout:
            out["shout"] = shout
        return out

    # ---------------------------------------------------------- narrative
    def _make_note(self, day, iso, risk_on, breadth, tret, tlevel, n_pos,
                   ramadan, events, rank_codes, view, names, my_dd, equity):
        ev = {e[0] if isinstance(e, tuple) else e for e in events}
        if "bunker_in" in ev:
            return (f"Equity down {my_dd:.1%} from the peak. I have seen this movie — "
                    f"February 2006, the hall went silent in one afternoon. To the bunker. "
                    f"{self._proverb()}")
        if "bunker_out" in ev:
            return (f"TASI back over its 200-line, breadth {breadth:.0%}. The old man "
                    f"unbolts the door and counts his SAR {equity:,.0f}. {self._proverb()}")
        for e in events:
            if isinstance(e, tuple) and e[0] == "stop":
                _, c, upnl = e
                return (f"Cut {names.get(c, c)} at {upnl:+.1%}. It stings, but in 2006 the men "
                        f"who 'waited for it to come back' are still waiting. {self._proverb()}")
            if isinstance(e, tuple) and e[0] == "aramco_sold":
                return (f"I sold Aramco under 95% of its 200-day line at {e[1]:.2f}. "
                        f"My heart is heavier than my wallet today. Even family must obey the trend.")
        for e in events:
            if isinstance(e, tuple) and e[0] == "bought":
                c = e[1][0]
                r = view.get(c, {})
                r12 = r.get("ret_12m", float("nan"))
                return (f"New week, new camels for the caravan: {', '.join(names.get(x, x) for x in e[1])}. "
                        f"{names.get(c, c)} carries {r12:+.0%} over twelve months. "
                        f"I ride winners; I do not marry them. {self._proverb()}")
            if isinstance(e, tuple) and e[0] == "cut":
                c = e[1]
                return (f"{names.get(c, c)} slipped under its 50-day line — the souq whispered, "
                        f"I listened, it is gone. {self._proverb()}")
            if isinstance(e, tuple) and e[0] == "anchor":
                return (f"Topped up the Aramco anchor at {e[1]:.2f}, safe above its 200-line. "
                        f"Don't tell the majlis I smiled.")
        if ramadan:
            held = f"my {n_pos} names" if n_pos else "my cash"
            return (f"Ramadan tape: thin as broth. TASI {tlevel:,.0f}, breadth {breadth:.0%}. "
                    f"I hold {held} and my tongue. No new positions until Eid.")
        if abs(tret) >= 0.02:
            side = "bled" if tret < 0 else "roared"
            return (f"TASI {side} {tret:+.1%} to {tlevel:,.0f}. In 2006 we had days like this "
                    f"before breakfast. Grip the reins, check the stops. {self._proverb()}")
        book = (f"{n_pos} names in the book" if n_pos > 1
                else "one name in the book" if n_pos == 1 else "a book of cash")
        variants = [
            f"Quiet session. TASI {tlevel:,.0f}, breadth {breadth:.0%}, {book}. {self._proverb()}",
            f"Tea, tape, and the 200-day line — TASI at {tlevel:,.0f}, regime {'up' if risk_on else 'down'}. {self._proverb()}",
            (f"Top of my momentum list today: {names.get(rank_codes[0], rank_codes[0])}. "
             f"The strong get stronger — that is the whole religion of trend. {self._proverb()}")
            if rank_codes else
            f"Not one name passes my trend filter today. Breadth {breadth:.0%}. The desert is empty. {self._proverb()}",
            f"Equity SAR {equity:,.0f}, drawdown {my_dd:.1%} off the peak. The old man endures. {self._proverb()}",
            f"TASI {tret:+.2%} to {tlevel:,.0f}. Nothing to do — and doing nothing is a position. {self._proverb()}",
        ]
        return variants[day % len(variants)]

    def _make_shout(self, day, iso, risk_on, regime_flip, ramadan_starts,
                    tret, events, names, ctx, equity, peak, breadth):
        since = day - self._last_shout
        dramatic = abs(tret) >= 0.025
        ev = {e[0] if isinstance(e, tuple) else e for e in events}
        shout = None
        if "bunker_in" in ev and since >= 2:
            shout = ("Ya jama'a, I lived February 2006 — from 20,000 to 7,000 while grown men wept "
                     "in the hall. My drawdown bell rang. Abu Shanab goes to cash. Close the door "
                     "the wind comes from, and rest.")
        elif "bunker_out" in ev and since >= 2:
            shout = (f"The index stands over its 200-day line again, breadth {breadth:.0%}. "
                     "The old man leaves the bunker. Slowly, slowly — the burnt hand fears the kettle.")
        elif regime_flip and since >= 3:
            shout = ("TASI reclaimed its 200-day line. The caravan moves — I buy strength, not stories."
                     if risk_on else
                     "TASI broke its 200-day line. I have smelled this smoke before, in 2006. "
                     "Cut your losers, ya shabab, before they cut you.")
        elif ramadan_starts and since >= 2:
            shout = ("Ramadan Kareem, ya jama'a. The tape goes thin as broth — no new positions "
                     "from me until Eid. He who trades the Ramadan chop donates to the brokers.")
        elif ("aramco_sold" in ev) and since >= 2:
            shout = "I sold my Aramco today. Forty years in the souq and my hands still shook. The trend spares no one."
        elif dramatic and since >= 2:
            if tret < 0:
                shout = (f"TASI {tret:+.1%} in one session. Calm down, ya shabab — in 2006 we lost that "
                         f"before the dallah was empty. Respect your stops and live to trade Sunday.")
            else:
                shout = (f"TASI {tret:+.1%}! The souq roars. Ride winners, but tie your camel — "
                         f"euphoria pays commissions, discipline pays grandchildren.")
        elif since >= 8:
            posts = ctx.get("majlis") or []
            if posts:
                avg = sum(p.get("sentiment", 0.0) for p in posts) / len(posts)
                if avg > 0.55 and not risk_on:
                    shout = ("The majlis is drunk on green candles while the index sits under its "
                             "200-day line. We were this cheerful in January 2006 too. Yalla, keep laughing.")
                elif avg < -0.5 and risk_on:
                    shout = ("All this wailing while the trend points up? The dogs bark and the "
                             "caravan moves on. Abu Shanab stays long.")
            if shout is None and equity >= peak and day - self._last_brag >= 21 and equity > 108_000:
                self._last_brag = day
                shout = (f"New high for the old man: SAR {equity:,.0f}. No rocket stocks, no whispers — "
                         f"just the 200-day line and a sharp knife for losers.")
        if shout:
            self._last_shout = day
        return shout


STRATEGY = AbuShanab()
