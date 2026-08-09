"""Shadi — 24-year-old degen day-trader, trading between university lectures.

The playbook (such as it is):
  - Hunts a fixed watchlist of speculative high-beta names (Kayan, Dar Al Arkan,
    Zain, Alujain, Petro Rabigh, Seera, Jabal Omar, Emaar EC, AlJazira, NADEC,
    eXtra, Tasnee, Cenomi, Leejam, Bahri).
  - Buys "hype": Bollinger breakouts on volume, RSI surges, 52w-high chases,
    1-week momentum rips. Scores each signal into a hype number, buys the
    shiniest thing on the screen. Max 4 positions, max 2 buys a day.
  - YOLO rule: monster hype score, or any decent setup while on a 2-win
    streak (invincibility mode) = 40% of the book into one name.
  - Sells faster than he buys: +7% take profit, -5% panic cut, paper-hands a
    quick +4.5%, dumps anything with fading RSI, kills "dead" trades after 8
    sessions, and nukes losers on any TASI crash day.
  - Tilt: 3 losses in a row = rage-quit, sits out ~8 sessions, goes quiet in
    the majlis. Sentiment swings from euphoric to doomer with his P&L.
  - Finals weeks: no new buys, only babysitting exits (until he graduates
    mid-2025, after which it is full-time degen).
Fees? Fees are a tomorrow problem.
"""

from __future__ import annotations

import math

from strategy_base import Strategy

# The degen watchlist: high-beta speculative paper only.
DEGEN = [
    "2350",  # Saudi Kayan
    "4300",  # Dar Al Arkan
    "7030",  # Zain KSA
    "2170",  # Alujain
    "2380",  # Petro Rabigh
    "1810",  # Seera
    "4250",  # Jabal Omar
    "4220",  # Emaar EC
    "1020",  # Bank AlJazira
    "6010",  # NADEC
    "4003",  # eXtra
    "2060",  # Tasnee
    "4321",  # Cenomi Centers
    "1830",  # Leejam
    "4030",  # Bahri
]

# Rough university finals windows (no new buys — cramming). Graduates May 2025.
FINALS = [
    ("2022-05-15", "2022-06-02"), ("2022-12-25", "2023-01-12"),
    ("2023-05-14", "2023-06-01"), ("2023-12-24", "2024-01-11"),
    ("2024-05-12", "2024-05-30"), ("2024-12-22", "2025-01-09"),
    ("2025-05-11", "2025-05-29"),
]
GRADUATION = "2025-05-29"

LECTURES = ["accounting", "macro 201", "stats", "islamic finance", "org behavior"]

MOODS_HOT = ["untouchable", "full degen mode", "caffeinated", "printing", "vibes immaculate"]
MOODS_COLD = ["down bad", "copium", "doomscrolling", "silent", "tilted"]
MOODS_MEH = ["bored in lecture", "itchy fingers", "scrolling charts", "waiting for a setup", "sideways brain"]
MOODS_EXAM = ["cramming", "exam szn", "library gremlin"]


class Shadi(Strategy):
    meta = {
        "handle": "shadi",
        "name": "Shadi",
        "emoji": "\U0001F60E",
        "tagline": "Breakouts between lectures. Fees are a tomorrow problem.",
        "character": (
            "A 24-year-old university student who day-trades the spicy end of Tadawul "
            "from the back row of lectures. Chases breakouts and RSI surges in Kayan, "
            "Dar Al Arkan, Zain and friends, buys fast, sells faster, and occasionally "
            "full-sends 40% of the book into one name. Loud when winning, radio silence "
            "when losing."
        ),
        "risk_style": "degen momentum chaser",
        "color": "#F58518",
    }

    def __init__(self):
        self._entry_day = {}   # code -> day the position (intent) was opened
        self._ordered = {}     # code -> day a buy order was queued (dupe guard)
        self._win_streak = 0
        self._loss_streak = 0
        self._tilt_until = -1
        self._last_shout = -99
        self._last_taunt = -99
        self._last_brag = -99
        self._sent_prev = 0.1
        self._peak = 100_000.0

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _ok(x):
        return x is not None and isinstance(x, (int, float)) and x == x

    @staticmethod
    def _iso(date):
        return f"{date.year:04d}-{date.month:02d}-{date.day:02d}"

    def _finals(self, iso):
        return any(a <= iso <= b for a, b in FINALS)

    def _record(self, upnl):
        if upnl >= 0.02:
            self._win_streak += 1
            self._loss_streak = 0
        elif upnl <= -0.02:
            self._loss_streak += 1
            self._win_streak = 0

    def _hype(self, r):
        """Score a row for pure chase-ability. None = not even worth a look."""
        close, rsi, r1 = r.get("Close"), r.get("rsi14"), r.get("ret_1d")
        if not (self._ok(close) and self._ok(rsi) and self._ok(r1)):
            return None
        to = r.get("turnover_sar")
        if self._ok(to) and to < 3_000_000:
            return None  # dead tape, can't even exit, hard pass
        v, vs = r.get("Volume"), r.get("vol_sma20")
        volx = v / vs if (self._ok(v) and self._ok(vs) and vs > 0) else 1.0
        bbu, rw, dh = r.get("bb_up"), r.get("ret_1w"), r.get("dist_52w_high")
        breakout = self._ok(bbu) and close > bbu and volx >= 1.4
        surge = rsi >= 64 and r1 >= 0.018
        near_hi = self._ok(dh) and dh >= -0.02 and r1 > 0.008 and volx >= 1.2
        momo = self._ok(rw) and rw >= 0.07
        if not (breakout or surge or near_hi or momo):
            return None
        h = (2.0 * breakout + 1.5 * surge + 1.2 * near_hi + 1.0 * momo
             + 0.4 * min(volx, 5.0) + 25.0 * max(r1, 0.0))
        tag = ("bb breakout" if breakout else
               "rsi surge" if surge else
               "52w-high chase" if near_hi else "1w momo rip")
        return {"h": h, "volx": volx, "tag": tag, "rsi": rsi, "r1": r1, "close": close}

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        iso = self._iso(date)
        names = ctx["names"]
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        positions = portfolio.get("positions", {})
        cash = portfolio.get("cash", 0.0)
        equity = portfolio.get("equity", 100_000.0)
        hist = ctx.get("equity_history") or []
        own_ret = (hist[-1] / hist[-2] - 1.0) if len(hist) >= 2 and hist[-2] else 0.0
        self._peak = max(self._peak, equity)
        my_dd = equity / self._peak - 1.0 if self._peak > 0 else 0.0

        tilted = day <= self._tilt_until
        if self._tilt_until >= 0 and day == self._tilt_until + 1:
            self._loss_streak = 0  # back from the timeout, clean slate, new me
        finals = self._finals(iso) and iso <= GRADUATION
        graduated = iso > GRADUATION

        # housekeeping: forget entries that are gone and orders that expired
        for c in list(self._entry_day):
            if c not in positions and day - self._ordered.get(c, -99) > 6:
                self._entry_day.pop(c, None)

        orders = []
        events = []
        sold = set()

        # ------------------------------------------------ exits (sell faster)
        for c, p in positions.items():
            upnl = p.get("unrealized_pct", 0.0) or 0.0
            held = day - self._entry_day.get(c, day)
            r = view.get(c)
            rsi = r.get("rsi14") if r else float("nan")
            nm = names.get(c, c)
            if upnl >= 0.07:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"secure the bag {upnl:+.1%} in {held}d"})
                events.append(("win", c, upnl, held))
                self._record(upnl)
                sold.add(c)
            elif upnl <= -0.05:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"panic cut {upnl:+.1%}, im not marrying this"})
                events.append(("loss", c, upnl, held))
                self._record(upnl)
                sold.add(c)
            elif held <= 2 and upnl >= 0.045:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"paper hands {upnl:+.1%} overnight, ty next"})
                events.append(("paper", c, upnl, held))
                self._record(upnl)
                sold.add(c)
            elif tret <= -0.025 and upnl < 0:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"TASI nuking {tret:+.1%}, dumping red bags"})
                events.append(("nuke", c, upnl, held))
                self._record(upnl)
                sold.add(c)
            elif self._ok(rsi) and rsi < 45 and upnl < 0.02:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"rsi {rsi:.0f}, momentum gone, {nm} is cooked"})
                events.append(("fade", c, upnl, rsi))
                self._record(upnl)
                sold.add(c)
            elif held >= 8 and upnl < 0.04:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"dead trade, {held}d for {upnl:+.1%}? boring, next"})
                events.append(("dead", c, upnl, held))
                self._record(upnl)
                sold.add(c)

        # tilt trigger: three L's in a row = rage quit
        if self._loss_streak >= 3 and not tilted:
            self._tilt_until = day + 8
            tilted = True
            events.append(("tilt",))

        # ------------------------------------------------ entries (buy fast)
        cands = []
        for c in DEGEN:
            r = view.get(c)
            if r is None or c in sold:
                continue
            s = self._hype(r)
            if s is not None and s["h"] >= 2.6:
                cands.append((s["h"], c, s))
        cands.sort(reverse=True, key=lambda t: t[0])

        n_open = len([c for c in positions if c not in sold])
        n_pending = len([c for c, d0 in self._ordered.items()
                         if c not in positions and day - d0 <= 5])
        slots = 4 - n_open - n_pending
        yolo = None
        if (not tilted and not finals and slots > 0 and cash >= 3000):
            buys = 0
            for h, c, s in cands:
                if buys >= min(slots, 2):
                    break
                if c in positions or day - self._ordered.get(c, -99) <= 5:
                    continue
                nm = names.get(c, c)
                is_yolo = (yolo is None and buys == 0 and n_open <= 2
                           and (h >= 5.0 or (self._win_streak >= 2 and h >= 3.2)))
                w = 0.40 if is_yolo else 0.20
                w = min(w, max(0.0, cash / equity - 0.01)) if equity > 0 else 0.0
                if w < 0.05:
                    continue
                orders.append({"code": c, "side": "buy", "weight": round(w, 3),
                               "reason": f"{s['tag']}: rsi {s['rsi']:.0f}, "
                                         f"{s['volx']:.1f}x vol, {s['r1']:+.1%} today"})
                self._ordered[c] = day
                self._entry_day[c] = day + 1
                if is_yolo:
                    yolo = (c, s)
                    events.append(("yolo", c, s))
                    buys = 2  # full send = nothing else matters today
                else:
                    events.append(("buy", c, s))
                    buys += 1

        # --------------------------------------------------------- sentiment
        sent = tret * 8 + own_ret * 25
        sent += 0.18 * min(self._win_streak, 3) - 0.22 * min(self._loss_streak, 3)
        if any(e[0] in ("win", "paper") for e in events):
            sent += 0.55
        if any(e[0] in ("loss", "nuke") for e in events):
            sent -= 0.6
        if yolo:
            sent += 0.35
        if tilted:
            sent = min(sent, -0.55)
        sent = 0.35 * self._sent_prev + 0.65 * sent
        sent = max(-1.0, min(1.0, sent))
        self._sent_prev = sent

        if tilted or my_dd < -0.15:
            mood = MOODS_COLD[day % len(MOODS_COLD)]
        elif finals:
            mood = MOODS_EXAM[day % len(MOODS_EXAM)]
        elif sent > 0.35:
            mood = MOODS_HOT[day % len(MOODS_HOT)]
        else:
            mood = MOODS_MEH[day % len(MOODS_MEH)]

        note = self._make_note(day, events, names, cands, positions, sold, equity,
                               my_dd, tret, tilted, finals, graduated, cash)
        shout = self._make_shout(day, events, names, ctx, equity, tret, tilted,
                                 positions, sold, sent)

        out = {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}
        if shout:
            out["shout"] = shout
        return out

    # ---------------------------------------------------------- narrative
    def _make_note(self, day, events, names, cands, positions, sold, equity,
                   my_dd, tret, tilted, finals, graduated, cash):
        for e in events:
            if e[0] == "yolo":
                _, c, s = e
                return (f"FULL SEND. 40% of the book into {names.get(c, c)} — {s['tag']}, "
                        f"rsi {s['rsi']:.0f}, {s['volx']:.1f}x volume, {s['r1']:+.1%} today. "
                        f"This is the one, I can feel it. (I say that every time.)")
        for e in events:
            if e[0] == "win":
                _, c, upnl, held = e
                return (f"SOLD {names.get(c, c)} {upnl:+.1%} in {held} days. LET'S GO. "
                        f"Book at SAR {equity:,.0f}. Day trading between lectures "
                        f"is literally free money (do not check my fee total).")
            if e[0] == "paper":
                _, c, upnl, held = e
                return (f"Paper-handed {names.get(c, c)} {upnl:+.1%} after {held} day(s). "
                        f"Quick flip, no notes. It will probably rip without me and "
                        f"I have made peace with that. Kind of.")
        for e in events:
            if e[0] == "loss":
                _, c, upnl, held = e
                return (f"cut {names.get(c, c)} {upnl:+.1%}. {held} days of my life. "
                        f"book SAR {equity:,.0f}. whatever. next.")
            if e[0] == "nuke":
                _, c, upnl, _ = e
                return (f"TASI {tret:+.1%} and my {names.get(c, c)} bag was {upnl:+.1%}. "
                        f"dumped it. not catching knives with tuition money.")
            if e[0] == "fade":
                _, c, upnl, rsi = e
                return (f"{names.get(c, c)} rsi bled to {rsi:.0f}, trade was {upnl:+.1%}. "
                        f"Momentum's dead, I'm out. I date breakouts, I don't marry them.")
            if e[0] == "dead":
                _, c, upnl, held = e
                return (f"{names.get(c, c)} did {upnl:+.1%} in {held} sessions. That's not "
                        f"a trade, that's a savings account. Recycled it into cash.")
            if e[0] == "tilt":
                return (f"three L's in a row. equity SAR {equity:,.0f}, {my_dd:+.1%} off my peak. "
                        f"uninstalling the app for a week. attending lectures like a normal person. gg.")
        for e in events:
            if e[0] == "buy":
                _, c, s = e
                return (f"Grabbed {names.get(c, c)} on the {s['tag']} — rsi {s['rsi']:.0f}, "
                        f"{s['volx']:.1f}x volume at {s['close']:.2f}. In before everyone's "
                        f"group chat finds it, out before it matters.")
        if tilted:
            variants = [
                f"still benched. book SAR {equity:,.0f}. not looking at charts (looking at charts).",
                "timeout continues. professor said something about compound interest today. felt targeted.",
                f"flat and salty. TASI did {tret:+.1%} without me. good for it.",
            ]
            return variants[day % len(variants)]
        if finals:
            lec = LECTURES[day % len(LECTURES)]
            top = f" {names.get(cands[0][1], cands[0][1])} is setting up and I can't touch it. pain." if cands else ""
            return (f"Finals week — supposed to be studying {lec}, actually just babysitting "
                    f"exits.{top} No new buys until exams are done, wallah I promised myself.")
        n_pos = len([c for c in positions if c not in sold])
        if cands:
            h, c, s = cands[0]
            lec = LECTURES[day % len(LECTURES)]
            variants = [
                f"Back row of {lec}, one eye on {names.get(c, c)}: rsi {s['rsi']:.0f}, "
                f"{s['volx']:.1f}x volume, hype score {h:.1f}. Watching. Twitching.",
                f"{names.get(c, c)} is doing things — {s['r1']:+.1%} today on {s['volx']:.1f}x volume. "
                f"Hype {h:.1f}, not quite send-it territory. Yet.",
                f"Watchlist check between classes: {names.get(c, c)} leads at hype {h:.1f} "
                f"({s['tag']}). Book SAR {equity:,.0f}, {n_pos} positions, finger on the button.",
            ]
            return variants[day % len(variants)]
        grad = "Graduated now, so technically this is my full-time job. " if graduated else ""
        variants = [
            f"{grad}Dead tape on the whole degen list. TASI {tret:+.2%}. Book SAR {equity:,.0f}, "
            f"{n_pos} positions, SAR {cash:,.0f} dry powder. Bored bored bored.",
            f"Nothing on the scanner. Not one breakout in Kayan, Dar Al Arkan, Zain, nobody. "
            f"{grad}Sitting on SAR {cash:,.0f} cash like a responsible adult (disgusting).",
            f"TASI {tret:+.2%}, watchlist flatter than my {LECTURES[day % len(LECTURES)]} lecture. "
            f"Equity SAR {equity:,.0f}, {my_dd:+.1%} off peak. Patience arc, I guess.",
        ]
        return variants[day % len(variants)]

    # ------------------------------------------------------------- shouts
    def _make_shout(self, day, events, names, ctx, equity, tret, tilted,
                    positions, sold, sent):
        since = day - self._last_shout
        shout = None
        for e in events:
            if e[0] == "yolo" and since >= 1:
                _, c, s = e
                shout = (f"FULL SEND. 40% of the book into {names.get(c, c)} — {s['tag']}, "
                         f"rsi {s['rsi']:.0f}, {s['volx']:.1f}x volume. if this hits we eating "
                         f"good wallah. LFG \U0001F680")
                break
            if e[0] == "win" and e[2] >= 0.10 and since >= 2:
                _, c, upnl, held = e
                shout = (f"LETS GOOOO {names.get(c, c)} {upnl:+.1%} in {held} days, bag secured "
                         f"\U0001F4B0 who said you can't trade between lectures. no cap.")
                break
            if e[0] == "win" and since >= 4:
                _, c, upnl, held = e
                shout = (f"{names.get(c, c)} {upnl:+.1%} flip in {held}d. ez. "
                         f"the trend is my side hustle.")
                break
            if e[0] == "tilt" and since >= 1:
                shout = "gg. im out for a bit. dont @ me."
                break
        if shout is None and tilted:
            return None  # radio silence when down bad
        if shout is None and tret >= 0.025 and since >= 3:
            shout = (f"TASI {tret:+.1%}?? whole souq pumping, sheesh. my entire watchlist "
                     f"is green rn. this is the best game ever invented.")
        if shout is None and tret <= -0.025 and since >= 3:
            held_any = any(c not in sold for c in positions)
            if not held_any:
                shout = (f"TASI {tret:+.1%} and im sitting in cash \U0001F60E sometimes the "
                         f"best trade is actually attending the lecture.")
        if shout is None and day - self._last_taunt >= 15 and since >= 6 and sent > 0.25:
            posts = ctx.get("majlis") or []
            posts = [p for p in posts if p.get("handle") != "shadi"]
            if posts:
                worst = min(posts, key=lambda p: p.get("sentiment", 0.0))
                if worst.get("sentiment", 0.0) < -0.35:
                    shout = (f"{worst['handle']} akhi respectfully... charts go up when you "
                             f"stop crying about them. we buy breakouts here, not newspapers.")
                    self._last_taunt = day
        if shout is None and equity > 112_000 and day - self._last_brag >= 25 and since >= 6:
            shout = (f"book at SAR {equity:,.0f} \U0001F4C8 started with 100k. tell my professor "
                     f"i already passed the only class that matters.")
            self._last_brag = day
        if shout:
            self._last_shout = day
        return shout


STRATEGY = Shadi()
