"""Abu Fahad — the contrarian falcon. He buys blood and sells euphoria.

The hunt, as actual rules:
  - PREY (buys): names near their 52-week low, in deep drawdown, RSI still
    under 50, liquid (turnover), AND back above their sma20 — the falcon
    strikes wounded game, not falling bodies. Prey fallen more than ~55% from
    its high is dead, not wounded — he refuses it. Max two names per sector
    (one dying herd is one dying herd). One strike per day, patience between.
  - SECOND STRIKE: one average-down per name if it falls a further 10% below
    his cost but stands back above its sma20.
  - RELEASE (sells): a holding that heals back near its 52-week high is
    released — the falcon does not chase healthy game. A holding stretched
    25%+ above its sma200 with RSI > 75 is euphoric — killed on the spot.
    Winners over +30% with hot RSI get half harvested once.
  - CARRION: a position rotting 20% below cost after 30 sessions is dropped.
    A name that went carrion is a poisoned well: banned for 200 sessions,
    banned forever the second time. The falcon remembers.
  - FADING THE MAJLIS: he averages yesterday's posts from the OTHER agents.
    Consensus >= +0.5 -> he stops buying and trims winners into their cheering.
    Consensus <= -0.4 -> he hunts aggressively (more slots, looser wounds,
    bigger talons). Market-wide blood (breadth <= 18%, index RSI <= 30 or
    index drawdown <= -18%) also flips him aggressive; breadth >= 85% with a
    hot index RSI reads as euphoria even if the majlis is silent.
  - Otherwise he sits on the glove, hooded, holding cash for months.
"""

from __future__ import annotations

import math

from strategy_base import Strategy

WISDOM = [
    "Patience is the falcon's first feather.",
    "He who hurries to the well drinks sand.",
    "A falcon does not chase every sparrow; it waits for the wounded houbara.",
    "What the flood takes, the patient man finds downstream.",
    "He who buys what all men love pays for their love too.",
    "When every tent cheers, fold yours.",
    "Blood on the sand is the falcon's invitation.",
    "The dune that rose highest feeds the wind first.",
    "Fear is a merchant: he sells cheap at dawn and buys dear at dusk.",
    "The wise hunter counts the herd while others count their wounds.",
    "In the empty desert, water is cheap only at noon.",
    "The crowd runs from the storm; the sands drink the rain.",
]

MOODS_CALM = ["hooded and patient", "circling high", "still as stone",
              "reading the wind", "sharpening talons"]
MOODS_HUNT = ["talons out", "diving", "blood-scent on the wind",
              "feasting", "eyes on the wounded"]
MOODS_WARY = ["wary of the cheering", "backing off the kill",
              "watching the festival", "counting the crowd", "folding the tent"]


class AbuFahad(Strategy):
    meta = {
        "handle": "abu_fahad",
        "name": "Abu Fahad",
        "emoji": "🦅",
        "tagline": "The falcon eats what the crowd leaves behind.",
        "character": (
            "A calm, cryptic contrarian who hunts the Tadawul like a falconer works "
            "the dunes: he buys names bleeding near their 52-week lows and sells the "
            "ones the crowd has kissed 25% above their 200-day line. He reads the "
            "majlis only to lean against it, and he can sit on cash for months, "
            "hooded, quoting the desert."
        ),
        "risk_style": "patient contrarian / mean-reversion",
        "color": "#E45756",
    }

    def __init__(self):
        self._entry = {}          # code -> day_index of first strike
        self._adds = {}           # code -> number of average-downs done
        self._trimmed = set()     # codes already half-harvested
        self._cooldown = {}       # code -> day of last full exit
        self._carrion_ct = {}     # code -> times it went carrion (poisoned wells)
        self._pend_buy = {}       # code -> day a buy was queued
        self._pend_sell = {}      # code -> day a sell was queued
        self._last_buy_day = -99
        self._last_shout = -99
        self._last_fade_trim = -99
        self._widx = 0

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _ok(x):
        return isinstance(x, (int, float)) and x == x

    def _wisdom(self):
        self._widx += 1
        return WISDOM[self._widx % len(WISDOM)]

    # --------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx.get("names", {})
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        positions = portfolio.get("positions", {})
        cash = portfolio.get("cash", 0.0)
        equity = portfolio.get("equity", 0.0) or 1.0

        # --- the index's own pulse ---
        tasi = view.get("TASI") or view.get("TASI_SR") or {}
        tasi_rsi = tasi.get("rsi14", float("nan"))
        tasi_dd = tasi.get("drawdown", float("nan"))
        tlevel = tasi.get("AdjClose", float("nan"))

        # --- read the majlis, then lean against it ---
        posts = [p for p in (ctx.get("majlis") or [])
                 if p.get("handle") != self.meta["handle"]]
        crowd = (sum(float(p.get("sentiment", 0.0)) for p in posts) / len(posts)
                 ) if posts else 0.0
        n_posts = len(posts)

        blood_market = (breadth <= 0.18
                        or (self._ok(tasi_rsi) and tasi_rsi <= 30)
                        or (self._ok(tasi_dd) and tasi_dd <= -0.18))
        aggressive = (n_posts > 0 and crowd <= -0.40) or blood_market
        crowd_euphoric = n_posts > 0 and crowd >= 0.50
        fever = breadth >= 0.85 and self._ok(tasi_rsi) and tasi_rsi >= 70
        euphoric = crowd_euphoric or fever

        # --- housekeeping of my own book-keeping ---
        for c in list(self._pend_buy):
            if c in positions or day - self._pend_buy[c] > 6:
                self._pend_buy.pop(c, None)
        for c in list(self._pend_sell):
            if day - self._pend_sell[c] > 6:
                self._pend_sell.pop(c, None)
        for c in list(self._entry):
            if c not in positions and c not in self._pend_buy:
                # position fully gone: remember the kill, clear the rest
                self._cooldown.setdefault(c, day)
                self._entry.pop(c, None)
                self._adds.pop(c, None)
                self._trimmed.discard(c)

        orders = []
        events = []

        # ------------------------------------------------- exits: the ledger
        for c, p in positions.items():
            if c in self._pend_sell:
                continue
            r = view.get(c)
            if r is None:
                continue  # halted: the falcon waits over the empty burrow
            upnl = p.get("unrealized_pct", 0.0)
            rsi = r.get("rsi14", float("nan"))
            adj = r.get("AdjClose", float("nan"))
            s200 = r.get("sma200", float("nan"))
            d52h = r.get("dist_52w_high", float("nan"))
            held_for = day - self._entry.get(c, day)

            # euphoria kill: stretched far above sma200 with RSI > 75
            if self._ok(adj) and self._ok(s200) and s200 > 0 and self._ok(rsi) \
                    and adj > s200 * 1.25 and rsi > 75:
                stretch = adj / s200 - 1.0
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"euphoria: {stretch:+.0%} over sma200, RSI {rsi:.0f}"})
                self._pend_sell[c] = day
                events.append(("kill", c, upnl, rsi, stretch))
                continue
            # healed game: back near its 52-week high — release it
            if self._ok(d52h) and d52h >= -0.05 and upnl > 0:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"healed: {d52h:.0%} off 52w-high, +{upnl:.0%} on cost"})
                self._pend_sell[c] = day
                events.append(("release", c, upnl))
                continue
            # carrion: still rotting long after the strike
            if upnl <= -0.20 and held_for >= 30:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"carrion after {held_for} sessions: {upnl:+.0%}"})
                self._pend_sell[c] = day
                self._carrion_ct[c] = self._carrion_ct.get(c, 0) + 1
                events.append(("carrion", c, upnl))
                continue
            # half-harvest a hot winner, once
            if c not in self._trimmed and upnl >= 0.30 and self._ok(rsi) and rsi >= 60:
                orders.append({"code": c, "side": "sell", "fraction": 0.5,
                               "reason": f"harvest half at {upnl:+.0%}, RSI {rsi:.0f}"})
                self._trimmed.add(c)
                events.append(("harvest", c, upnl))

        # fade an euphoric crowd: trim winners into their cheering
        if euphoric and day - self._last_fade_trim >= 10:
            why = (f"majlis cheers at {crowd:+.2f}; I sell to them" if crowd_euphoric
                   else f"fever tape: breadth {breadth:.0%}, TASI RSI {tasi_rsi:.0f}")
            faded = False
            for c, p in positions.items():
                if c in self._pend_sell or c in self._trimmed:
                    continue
                if p.get("unrealized_pct", 0.0) > 0.05:
                    orders.append({"code": c, "side": "sell", "fraction": 0.5,
                                   "reason": why})
                    self._trimmed.add(c)
                    faded = True
            if faded:
                self._last_fade_trim = day
                events.append(("fade_sell", crowd, crowd_euphoric))

        # -------------------------------------------------- the hunt: buys
        # thresholds loosen when the crowd despairs or the market bleeds
        dd_min = -0.20 if aggressive else -0.28    # wound must be at least this deep
        dd_dead = -0.62 if aggressive else -0.55   # fallen further = dead, not wounded
        low_max = 0.25 if aggressive else 0.15
        rsi_max = 55 if aggressive else 48
        turn_min = 2e6 if aggressive else 3e6
        max_pos = 7 if aggressive else 5
        slot_w = 0.20 if aggressive else 0.16
        gap = 0 if aggressive else 4
        strikes_today = 2 if aggressive else 1

        sectors = ctx.get("sectors", {})
        sector_ct = {}
        for c in list(positions) + list(self._pend_buy):
            s = sectors.get(c, "?")
            sector_ct[s] = sector_ct.get(s, 0) + 1

        prey = []
        for c, r in view.items():
            if c in ("TASI", "TASI_SR"):
                continue
            dd = r.get("drawdown", float("nan"))
            d52l = r.get("dist_52w_low", float("nan"))
            rsi = r.get("rsi14", float("nan"))
            turn = r.get("turnover_sar", float("nan"))
            adj = r.get("AdjClose", float("nan"))
            s20 = r.get("sma20", float("nan"))
            if not all(self._ok(x) for x in (dd, d52l, rsi, turn, adj, s20)):
                continue
            if (dd_dead <= dd <= dd_min and d52l <= low_max and rsi <= rsi_max
                    and turn >= turn_min and adj > s20):
                score = -dd + (rsi_max - rsi) / 100.0 + max(0.0, low_max - d52l)
                prey.append((score, c, dd, rsi, d52l))
        prey.sort(reverse=True)

        can_hunt = (not euphoric and cash > 2500
                    and day - self._last_buy_day >= gap)
        struck = []
        if can_hunt:
            n_book = len(positions) + len(self._pend_buy)
            for score, c, dd, rsi, d52l in prey:
                if len(struck) >= strikes_today or n_book >= max_pos:
                    break
                if c in positions or c in self._pend_buy or c in self._pend_sell:
                    continue
                poisoned = self._carrion_ct.get(c, 0)
                if poisoned >= 2:
                    continue  # the falcon remembers the poisoned well, forever
                ban = 200 if poisoned == 1 else 25
                if day - self._cooldown.get(c, -99) < ban:
                    continue
                if sector_ct.get(sectors.get(c, "?"), 0) >= 2:
                    continue  # one dying herd is one dying herd
                orders.append({"code": c, "side": "buy", "weight": slot_w,
                               "reason": f"blood: dd {dd:.0%}, RSI {rsi:.0f}, "
                                         f"{d52l:.0%} off 52w-low, back over sma20"})
                self._pend_buy[c] = day
                self._entry[c] = day
                self._adds.setdefault(c, 0)
                sector_ct[sectors.get(c, "?")] = sector_ct.get(sectors.get(c, "?"), 0) + 1
                struck.append((c, dd, rsi, d52l))
                n_book += 1
            if struck:
                self._last_buy_day = day
                events.append(("strike", struck, aggressive))

        # second strike: one average-down per wounded holding that found its feet
        if not euphoric and cash > 2500:
            for c, p in positions.items():
                if self._adds.get(c, 0) >= 1 or c in self._pend_sell or c in self._pend_buy:
                    continue
                r = view.get(c)
                if r is None:
                    continue
                upnl = p.get("unrealized_pct", 0.0)
                rsi = r.get("rsi14", float("nan"))
                turn = r.get("turnover_sar", float("nan"))
                adj = r.get("AdjClose", float("nan"))
                s20 = r.get("sma20", float("nan"))
                if upnl <= -0.10 and self._ok(rsi) and rsi <= 45 \
                        and self._ok(turn) and turn >= turn_min \
                        and self._ok(adj) and self._ok(s20) and adj > s20:
                    orders.append({"code": c, "side": "buy", "weight": slot_w * 0.5,
                                   "reason": f"second strike at {upnl:+.0%} below cost, RSI {rsi:.0f}"})
                    self._adds[c] = 1
                    self._pend_buy[c] = day
                    events.append(("second", c, upnl, rsi))
                    break  # one second strike per day is enough

        # ---------------------------------------------------- sentiment/mood
        sent = -0.7 * crowd
        sent += (0.5 - breadth) * 0.5
        sent -= max(-0.3, min(0.3, tret * 8))
        if prey:
            sent += 0.10 if len(prey) < 3 else 0.20
        if euphoric:
            sent = min(sent, -0.45)
        if aggressive:
            sent = max(sent, 0.35)
        sent = max(-0.95, min(0.95, sent))

        if euphoric:
            mood = MOODS_WARY[day % len(MOODS_WARY)]
        elif struck or aggressive:
            mood = MOODS_HUNT[day % len(MOODS_HUNT)]
        else:
            mood = MOODS_CALM[day % len(MOODS_CALM)]

        note = self._note(day, events, names, prey, positions, cash, equity,
                          breadth, crowd, n_posts, tret, tlevel, euphoric, aggressive)
        shout = self._shout(day, events, names, crowd, n_posts, tret, breadth,
                            euphoric, aggressive, cash, equity, len(positions))

        out = {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}
        if shout:
            out["shout"] = shout
        return out

    # ------------------------------------------------------------ narrative
    def _note(self, day, events, names, prey, positions, cash, equity,
              breadth, crowd, n_posts, tret, tlevel, euphoric, aggressive):
        nm = lambda c: names.get(c, c)
        for e in events:
            if e[0] == "strike":
                (c, dd, rsi, d52l) = e[1][0]
                how = "with both talons" if e[2] else "once, cleanly"
                return (f"Struck {nm(c)} {how}: down {dd:.0%} from its high, RSI {rsi:.0f}, "
                        f"{d52l:.0%} above its 52-week low but back over its 20-day line. "
                        f"The herd fled; the wounded one found its feet; the falcon dives. "
                        f"{self._wisdom()}")
            if e[0] == "kill":
                _, c, upnl, rsi, stretch = e
                return (f"{nm(c)} floats {stretch:+.0%} above its 200-day line at RSI {rsi:.0f}. "
                        f"The feast became a fever — sold all at {upnl:+.0%}. {self._wisdom()}")
            if e[0] == "release":
                _, c, upnl = e
                return (f"{nm(c)} is healed, back within a wingbeat of its 52-week high. "
                        f"I release it at {upnl:+.0%}. The falcon does not chase healthy game.")
            if e[0] == "carrion":
                _, c, upnl = e
                return (f"{nm(c)} was carrion, not prey: {upnl:+.0%}. Even the falcon "
                        f"leaves a poisoned carcass — and remembers the well it drank from. "
                        f"{self._wisdom()}")
            if e[0] == "harvest":
                _, c, upnl = e
                return (f"Half of {nm(c)} harvested at {upnl:+.0%}. The other half "
                        f"flies on. One wing carries the meat home.")
            if e[0] == "fade_sell":
                if e[2]:
                    return (f"The majlis hums at {e[1]:+.2f} and breadth is {breadth:.0%}. "
                            f"When every tent cheers, fold yours — I trimmed my winners "
                            f"into their cheering.")
                return (f"Fever on the tape: breadth {breadth:.0%} and the index RSI "
                        f"burning hot. No voices needed — I trimmed my winners before "
                        f"the sun turns. {self._wisdom()}")
            if e[0] == "second":
                _, c, upnl, rsi = e
                return (f"Second strike on {nm(c)} at {upnl:+.0%} below my cost, RSI {rsi:.0f}. "
                        f"A wounded houbara runs twice before it kneels.")
        n_pos = len(positions)
        if prey:
            _, c, dd, rsi, d52l = prey[0]
            watch = (f"I circle {nm(c)}: drawdown {dd:.0%}, RSI {rsi:.0f}, "
                     f"{d52l:.0%} off its 52-week low.")
        else:
            watch = "No blood on the sand today."
        stance = (f"Cash SAR {cash:,.0f} waits on the glove."
                  if equity > 0 and cash / equity > 0.15 else
                  f"The book is full — {n_pos} wounded names mending under my wing.")
        tstr = f"{tlevel:,.0f}" if tlevel == tlevel else "veiled in the haze"
        variants = [
            f"TASI {tstr}, breadth {breadth:.0%}. {watch} {stance} {self._wisdom()}",
            f"{watch} The majlis reads {crowd:+.2f} across {n_posts} voices — "
            f"I listen only to know where not to stand. {self._wisdom()}",
            f"Equity SAR {equity:,.0f}, {n_pos} wounded names on the ledger, "
            f"the rest is patience. {self._wisdom()}",
            f"TASI moved {tret:+.2%} to {tstr}. "
            f"{'The crowd celebrates; I count exits.' if tret > 0 else 'The crowd frets; I count entrances.'} "
            f"{watch}",
            f"Breadth {breadth:.0%}, index at {tstr}. "
            f"{'A fevered market — my talons stay sheathed.' if euphoric else ('The desert bleeds — good hunting weather.' if aggressive else 'Neither feast nor famine. The hood stays on.')} "
            f"{self._wisdom()}",
        ]
        return variants[day % len(variants)]

    def _shout(self, day, events, names, crowd, n_posts, tret, breadth,
               euphoric, aggressive, cash, equity, n_pos):
        since = day - self._last_shout
        nm = lambda c: names.get(c, c)
        shout = None
        for e in events:
            if e[0] == "strike" and since >= 6:
                c, dd, _, _ = e[1][0]
                shout = (f"The herd abandoned {nm(c)} at {dd:.0%} from its high. I did not. "
                         f"The falcon eats what the crowd leaves behind.")
            elif e[0] == "kill" and since >= 5:
                shout = (f"Sold {nm(e[1])} into your applause at {e[2]:+.0%}. "
                         f"The dune that rose highest feeds the wind first.")
            elif e[0] == "carrion" and since >= 6:
                shout = (f"I dropped {nm(e[1])} at {e[2]:+.0%}. A hunter admits when the "
                         f"kill was poisoned. Most of you never will.")
            elif e[0] == "fade_sell" and since >= 8:
                if e[2]:
                    shout = (f"Majlis consensus {crowd:+.2f}. I have seen this festival before — "
                             f"it ends with the tents on fire. Abu Fahad sells to your cheering.")
                else:
                    shout = (f"Breadth {breadth:.0%} and the index glowing hot. The higher the "
                             f"dune, the sooner the wind takes it. I lightened my book today.")
        if shout is None and n_posts > 0 and crowd <= -0.45 and since >= 8:
            shout = (f"You weep at {crowd:+.2f}, ya jama'a? Weep louder. Fear sells cheap "
                     f"at dawn — the falcon is buying with both talons.")
        elif shout is None and abs(tret) >= 0.025 and since >= 5:
            if tret < 0:
                shout = (f"TASI {tret:+.1%}. Blood on the sand at last. While you count wounds, "
                         f"I count the herd. Patience, then the dive.")
            else:
                shout = (f"TASI {tret:+.1%} and every voice in the majlis climbs an octave. "
                         f"When every tent cheers, fold yours.")
        elif shout is None and since >= 26:
            if equity > 0 and cash / equity > 0.30:
                shout = (f"Quiet, from the high air: cash SAR {cash:,.0f}, breadth {breadth:.0%}. "
                         f"A falcon is not idle when it circles — it is choosing.")
            else:
                shout = (f"Quiet, from the high air: {n_pos} wounded names mending in my book, "
                         f"breadth {breadth:.0%}. The falcon feeds while the crowd looks away.")
        if shout:
            self._last_shout = day
        return shout


STRATEGY = AbuFahad()
