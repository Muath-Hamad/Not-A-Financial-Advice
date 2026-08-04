"""Lulu — social-trading influencer. She doesn't trade the market, she trades the crowd.

The content calendar (a.k.a. strategy):
  - Reads the majlis every morning like it's her comment section. Computes the
    crowd's average sentiment (3-day smoothed = she's always one story behind).
    When no one else is posting she reads "her followers" instead — a proxy
    built from market breadth + the tape.
  - Crowd bullish (smoothed >= +0.10): deploys hard into whatever is trending —
    the best ret_1m names with real turnover. Max 5 positions, ~18-24% each,
    sized up when the crowd is euphoric. She buys tops proudly.
  - Crowd turns (smoothed <= -0.30): DUMPS EVERYTHING, posts about protecting
    the community, then takes a 5-session "mental health break" from the app
    and only comes back once the vibes recover.
  - FOMO rule: the day AFTER TASI rallies >1.5% she chases the two hottest
    names at the open, whatever the price. Everyone was posting rockets.
  - Content-driven exits: -8% stop (can't post that), screenshot half at +15%
    (content!), full dump when a name stops trending (ret_1m rolls over).
  - Wins are "called it, receipts in the group". Losses are the algo bros
    hunting her stops. Followers scale with the equity curve, obviously.
"""

from __future__ import annotations

import math
import random

from strategy_base import Strategy

MIN_TURNOVER = 5_000_000     # she only buys names her followers can also buy
HOT_RET1M = 0.04             # "trending" threshold
MAX_POS = 5
STOP = -0.08
SCREENSHOT = 0.15
CROWD_BUY = 0.08
CROWD_DUMP = -0.30
CROWD_BACK = -0.10
COOLDOWN = 5

MOODS_VIRAL = ["main character energy", "viral", "ring light on", "we move",
               "engagement UP"]
MOODS_OK = ["curating the feed", "soft-launching a position", "aesthetic",
            "reading the comments", "storyboarding"]
MOODS_BAD = ["posting through it", "shook", "comments OFF", "mental health break",
             "the DMs are a warzone"]


class Lulu(Strategy):
    meta = {
        "handle": "lulu",
        "name": "Lulu",
        "emoji": "\U0001F406",
        "tagline": "Trading the crowd, one story at a time. Link in bio.",
        "risk_style": "crowd-following FOMO momentum",
        "character": (
            "A social-trading influencer who treats the majlis like her comment "
            "section: she averages everyone's sentiment and follows it a day late, "
            "piling into whatever is trending when the crowd is hyped and dumping "
            "the whole portfolio the moment the vibes turn. Wins were 'called, "
            "receipts in the group'; losses are always the algo bros."
        ),
        "color": "#EECA3B",
    }

    def __init__(self):
        self._rng = random.Random(9051)     # fixed seed — the vibes are deterministic
        self._crowd_hist = []               # last few crowd averages (the lag)
        self._entry_day = {}                # code -> day bought (intent)
        self._ordered = {}                  # code -> day queued (dupe guard)
        self._screenshotted = set()         # names already half-sold for content
        self._cooldown_until = -1
        self._on_break = False
        self._fomo_armed = False
        self._fomo_ret = 0.0                # size of the TASI rip that armed the FOMO
        self._last_shout = -99
        self._last_filler = -99
        self._last_trim = -99
        self._sent_prev = 0.2
        self._peak = 100_000.0

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _ok(x):
        return isinstance(x, (int, float)) and x == x

    def _crowd_read(self, ctx):
        """Yesterday's majlis average; her 'followers' (breadth+tape) if it's quiet."""
        posts = [p for p in (ctx.get("majlis") or []) if p.get("handle") != "lulu"]
        if posts:
            raw = sum(float(p.get("sentiment", 0.0)) for p in posts) / len(posts)
            src = "majlis"
        else:
            breadth = ctx.get("breadth_sma50", 0.5)
            tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
            raw = (breadth - 0.5) * 1.6 + 6.0 * tret
            src = "followers"
        raw = max(-1.0, min(1.0, raw))
        self._crowd_hist.append(raw)
        if len(self._crowd_hist) > 3:
            self._crowd_hist.pop(0)
        return sum(self._crowd_hist) / len(self._crowd_hist), raw, src, posts

    def _hot_list(self, view, exclude):
        """The trending page: best 1-month movers with real liquidity."""
        out = []
        for c, r in view.items():
            if c == "TASI" or c in exclude:
                continue
            r1m, to, close = r.get("ret_1m"), r.get("turnover_sar"), r.get("Close")
            if not (self._ok(r1m) and self._ok(close)):
                continue
            if self._ok(to) and to < MIN_TURNOVER:
                continue
            if r1m < HOT_RET1M:
                continue
            out.append((r1m, c, r))
        out.sort(reverse=True, key=lambda t: t[0])
        return out

    def _followers(self, day, equity):
        """Follower count grows organically (day) and with receipts (equity)."""
        return max(1_200, 48_200 + day * 9 + int((equity - 100_000) * 1.4))

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx["names"]
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        positions = portfolio.get("positions", {})
        cash = portfolio.get("cash", 0.0)
        equity = portfolio.get("equity", 100_000.0)
        hist = ctx.get("equity_history") or []
        own_ret = (hist[-1] / hist[-2] - 1.0) if len(hist) >= 2 and hist[-2] else 0.0
        self._peak = max(self._peak, equity)
        followers = self._followers(day, equity)

        crowd, crowd_raw, crowd_src, posts = self._crowd_read(ctx)
        fomo_today = self._fomo_armed          # armed by yesterday's TASI rip
        fomo_ret = self._fomo_ret
        self._fomo_armed = tret >= 0.015       # today's rip -> chase at next open
        self._fomo_ret = tret if self._fomo_armed else 0.0

        cooling = day <= self._cooldown_until
        if self._on_break and not cooling and crowd >= CROWD_BACK:
            self._on_break = False             # vibes restored, she's back

        for c in list(self._entry_day):
            if c not in positions and day - self._ordered.get(c, -99) > 6:
                self._entry_day.pop(c, None)
                self._screenshotted.discard(c)

        orders, events = [], []
        sold = set()

        # ---------------------------------------------- THE DUMP (crowd turned)
        if crowd <= CROWD_DUMP and positions:
            for c, p in positions.items():
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"crowd sentiment {crowd:+.2f} — everybody OUT"})
                sold.add(c)
            self._cooldown_until = day + COOLDOWN
            self._on_break = True
            events.append(("dumpall", crowd, len(positions)))
        else:
            # ------------------------------------------- content-driven exits
            for c, p in positions.items():
                upnl = p.get("unrealized_pct", 0.0) or 0.0
                r = view.get(c)
                r1m = r.get("ret_1m") if r else float("nan")
                nm = names.get(c, c)
                if upnl <= STOP:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"{upnl:+.1%} — algo bros hunted my stop"})
                    events.append(("loss", c, upnl))
                    sold.add(c)
                elif self._ok(r1m) and r1m < -0.03 and upnl < 0.04:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"{nm} 1m {r1m:+.1%}, nobody posts about it anymore"})
                    events.append(("cold", c, upnl, r1m))
                    sold.add(c)
                elif upnl >= SCREENSHOT and c not in self._screenshotted:
                    orders.append({"code": c, "side": "sell", "fraction": 0.5,
                                   "reason": f"screenshot the {upnl:+.1%}, post it, keep half"})
                    self._screenshotted.add(c)
                    events.append(("screenshot", c, upnl))
                elif tret <= -0.02 and crowd < 0 and upnl < -0.03:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"TASI {tret:+.1%}, comments turning, cutting {nm}"})
                    events.append(("panic", c, upnl))
                    sold.add(c)
            # mild-bear trim: the position making her look worst has to go
            if CROWD_DUMP < crowd <= -0.10 and day - self._last_trim >= 3:
                live = [(p.get("unrealized_pct", 0.0) or 0.0, c)
                        for c, p in positions.items() if c not in sold]
                if live:
                    worst_u, worst_c = min(live)
                    if worst_u < -0.02:
                        orders.append({"code": worst_c, "side": "sell", "all": True,
                                       "reason": f"crowd {crowd:+.2f}, trimming the embarrassment "
                                                 f"({worst_u:+.1%})"})
                        events.append(("trim", worst_c, worst_u))
                        sold.add(worst_c)
                        self._last_trim = day

        # --------------------------------------------------------- entries
        held_or_sold = set(positions) | sold
        can_buy = (equity > 0 and not cooling and not self._on_break
                   and crowd > CROWD_DUMP and cash >= 2_000 and cash / equity > 0.06)
        hot = self._hot_list(view, exclude=sold)
        n_open = len([c for c in positions if c not in sold])
        n_pending = len([c for c, d0 in self._ordered.items()
                         if c not in positions and day - d0 <= 5])

        if can_buy and fomo_today and hot:
            chased = 0
            for r1m, c, r in hot:
                if chased >= 2:
                    break
                if c in held_or_sold or day - self._ordered.get(c, -99) <= 5:
                    continue
                orders.append({"code": c, "side": "buy", "weight": 0.15,
                               "reason": f"TASI ripped {fomo_ret:+.1%} yesterday, chasing "
                                         f"{names.get(c, c)} (1m {r1m:+.1%}) — everyone's "
                                         f"posting rockets"})
                self._ordered[c] = day
                self._entry_day[c] = day + 1
                events.append(("fomo", c, r1m, fomo_ret))
                chased += 1
                n_pending += 1

        if can_buy and crowd >= CROWD_BUY:
            slots = MAX_POS - n_open - n_pending
            base_w = 0.24 if crowd >= 0.35 else 0.18
            buys = 0
            for r1m, c, r in hot:
                if buys >= 2 or slots <= 0:
                    break
                if c in held_or_sold or day - self._ordered.get(c, -99) <= 5:
                    continue
                w = min(base_w, max(0.0, cash / equity - 0.02)) if equity > 0 else 0.0
                if w < 0.05:
                    break
                rsi = r.get("rsi14")
                rsi_txt = f", rsi {rsi:.0f} (who cares)" if self._ok(rsi) else ""
                orders.append({"code": c, "side": "buy", "weight": round(w, 3),
                               "reason": f"crowd {crowd:+.2f} bullish, {names.get(c, c)} is "
                                         f"trending: 1m {r1m:+.1%}{rsi_txt}"})
                self._ordered[c] = day
                self._entry_day[c] = day + 1
                events.append(("buy", c, r1m))
                buys += 1
                slots -= 1

        # -------------------------------------------------------- sentiment
        vibe = self._rng.uniform(-0.20, 0.35) + own_ret * 12   # follower vibes skew bullish
        sent = 0.55 * crowd + vibe
        if any(e[0] in ("buy", "fomo", "screenshot") for e in events):
            sent += 0.25
        if any(e[0] in ("loss", "panic", "trim") for e in events):
            sent -= 0.35
        if events and events[0][0] == "dumpall":
            sent = min(sent, -0.6)
        if self._on_break or cooling:
            sent = min(sent, -0.3)
        sent = 0.4 * self._sent_prev + 0.6 * sent
        sent = max(-1.0, min(1.0, sent))
        self._sent_prev = sent

        if self._on_break or cooling or sent < -0.3:
            mood = MOODS_BAD[day % len(MOODS_BAD)]
        elif sent > 0.3:
            mood = MOODS_VIRAL[day % len(MOODS_VIRAL)]
        else:
            mood = MOODS_OK[day % len(MOODS_OK)]

        note = self._make_note(day, events, names, crowd, crowd_src, hot, positions,
                               sold, equity, cash, tret, followers, cooling)
        shout = self._make_shout(day, events, names, posts, crowd, hot, equity,
                                 tret, followers, view, sent, cooling)

        out = {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}
        if shout:
            out["shout"] = shout
        return out

    # ---------------------------------------------------------- narrative
    def _make_note(self, day, events, names, crowd, crowd_src, hot, positions,
                   sold, equity, cash, tret, followers, cooling):
        src = "the majlis" if crowd_src == "majlis" else "my followers"
        for e in events:
            if e[0] == "dumpall":
                _, cr, n = e
                return (f"EVERYBODY OUT. {src.capitalize()} averaging {cr:+.2f} — when the "
                        f"comments turn, you don't argue with the comments. Liquidated all "
                        f"{n} positions, SAR {equity:,.0f} protected. Taking a break from "
                        f"the app. {followers:,} followers deserve better than red screenshots.")
        for e in events:
            if e[0] == "screenshot":
                _, c, upnl = e
                return (f"SCREENSHOTTED. {names.get(c, c)} {upnl:+.1%} — posted the P&L, kept "
                        f"half the position riding. I literally called this in the group. "
                        f"Receipts pinned. Book SAR {equity:,.0f}, followers {followers:,}.")
            if e[0] == "loss":
                _, c, upnl = e
                return (f"Cut {names.get(c, c)} at {upnl:+.1%}. The algo bros hunted my stop "
                        f"AGAIN — a human did not sell that bottom, a robot did. Not my fault, "
                        f"the market is rigged by machines. Moving on. SAR {equity:,.0f}.")
        for e in events:
            if e[0] == "fomo":
                _, c, r1m, frip = e
                return (f"TASI went {frip:+.1%} yesterday and my whole feed is rockets. "
                        f"Chasing {names.get(c, c)} at tomorrow's open (1m {r1m:+.1%}). Yes "
                        f"I'm late, but being early is just being wrong with extra steps.")
            if e[0] == "buy":
                _, c, r1m = e
                return (f"Crowd read: {src} at {crowd:+.2f}, so we deploy. Added "
                        f"{names.get(c, c)} — 1m {r1m:+.1%}, literally the trending page. "
                        f"You don't fight the timeline. Cash left SAR {cash:,.0f}.")
            if e[0] == "cold":
                _, c, upnl, r1m = e
                return (f"Dropped {names.get(c, c)} ({upnl:+.1%}) — 1m momentum rolled to "
                        f"{r1m:+.1%} and nobody is posting about it anymore. If it's not "
                        f"trending, it's not in my portfolio. Aesthetic must be maintained.")
            if e[0] == "panic":
                _, c, upnl = e
                return (f"TASI {tret:+.1%} and the DMs are a warzone. Cut {names.get(c, c)} "
                        f"at {upnl:+.1%} before the comment section does it for me. "
                        f"Capital protection is self-care.")
            if e[0] == "trim":
                _, c, upnl = e
                return (f"{src.capitalize()} gone quiet-bearish ({crowd:+.2f}). Trimmed "
                        f"{names.get(c, c)} at {upnl:+.1%} — can't have that on the grid. "
                        f"Curate your portfolio like you curate your feed.")
        if cooling or self._on_break:
            variants = [
                f"Mental health break, day {max(0, day - (self._cooldown_until - 5))}. "
                f"100% cash, SAR {equity:,.0f}. Crowd still at {crowd:+.2f}. "
                f"Journaling, hydrating, not looking at charts (looking at charts).",
                f"Still off the app (posting daily about being off the app). {src.capitalize()} "
                f"at {crowd:+.2f} — the vibes have not earned me back yet. SAR {equity:,.0f} safe.",
                f"Break continues. TASI {tret:+.2%} today, {followers:,} followers told me to "
                f"stay out and honestly? The comments are usually right eventually.",
            ]
            return variants[day % len(variants)]
        n_pos = len([c for c in positions if c not in sold])
        if hot:
            r1m, c, _ = hot[0]
            variants = [
                f"Morning crowd read: {src} at {crowd:+.2f}. Trending page says "
                f"{names.get(c, c)} (1m {r1m:+.1%}). {n_pos} positions, SAR {cash:,.0f} cash, "
                f"{followers:,} followers. Content calendar: full.",
                f"{names.get(c, c)} leads the feed at {r1m:+.1%}/1m. Crowd {crowd:+.2f} — "
                f"not hyped enough to add yet. I follow the timeline, I don't front-run it. "
                f"Book SAR {equity:,.0f}.",
                f"TASI {tret:+.2%}, crowd {crowd:+.2f}, hottest name {names.get(c, c)} "
                f"{r1m:+.1%}/1m. Holding {n_pos} names. Engagement stable, {followers:,} "
                f"followers. We wait for the vibes to commit.",
            ]
            return variants[day % len(variants)]
        variants = [
            f"Trending page is EMPTY — nothing over {HOT_RET1M:.0%}/1m with real volume. "
            f"Crowd {crowd:+.2f}, TASI {tret:+.2%}. {n_pos} positions, SAR {cash:,.0f} idle. "
            f"A slow feed is a sell signal on society.",
            f"Dead timeline today. {src.capitalize()} at {crowd:+.2f}, no hot names, "
            f"book SAR {equity:,.0f}. Posted a throwback P&L instead. Engagement farming "
            f"is also a strategy.",
            f"No momentum anywhere — TASI {tret:+.2%}, crowd {crowd:+.2f}. {followers:,} "
            f"followers and nothing to show them. Might do a Q&A about my {n_pos} bags.",
        ]
        return variants[day % len(variants)]

    # ------------------------------------------------------------- shouts
    def _make_shout(self, day, events, names, posts, crowd, hot, equity, tret,
                    followers, view, sent, cooling):
        since = day - self._last_shout
        shout = None
        for e in events:
            if e[0] == "dumpall" and since >= 1:
                _, cr, n = e
                pos_txt = f"all {n} positions" if n != 1 else "my last position"
                shout = (f"EVERYBODY OUT \U0001F6A8 crowd sentiment {cr:+.2f}, the comments "
                         f"have TURNED. selling {pos_txt} at the open. protect your "
                         f"capital, log off, drink water. this is the free advice.")
                break
            if e[0] == "screenshot" and since >= 2:
                _, c, upnl = e
                shout = (f"{names.get(c, c)} {upnl:+.1%} \U0001F4B0 I posted this name BEFORE "
                         f"it moved — receipts are pinned in the group. took the screenshot, "
                         f"half still riding. like and follow for the next one \U0001F406")
                break
            if e[0] == "loss" and since >= 2:
                _, c, upnl = e
                shout = (f"cut {names.get(c, c)} {upnl:+.1%}. and BEFORE the quants start "
                         f"typing: a human did not sell me that bottom. the algo bros hunted "
                         f"my stop to the tick. rigged. anyway new setup dropping tomorrow")
                break
            if e[0] == "fomo" and since >= 2:
                _, c, r1m, frip = e
                shout = (f"TASI did {frip:+.1%} yesterday and you're NOT long?? adding "
                         f"{names.get(c, c)} (1m {r1m:+.1%}) at the open. yes I'm chasing. "
                         f"chasing is just momentum with confidence \U0001F406\U0001F4C8")
                break
        if shout is None and events and events[0][0] == "buy" and since >= 3:
            _, c, r1m = events[0]
            shout = (f"crowd is at {crowd:+.2f} and the timeline never lies — loading "
                     f"{names.get(c, c)}, 1m {r1m:+.1%}. not financial advice but it is "
                     f"emotional support \U0001F49B")
        if shout is None and tret <= -0.02 and since >= 2 and not cooling:
            shout = (f"TASI {tret:+.1%}... the group chat is in shambles. crowd read "
                     f"{crowd:+.2f}. I'm watching ONE number: if the majlis average breaks "
                     f"{CROWD_DUMP:+.1f} we are ALL leaving together. stay hydrated")
        # engagement farming: tag whoever is loudest on the board
        if shout is None and since >= 5 and posts:
            bull = max(posts, key=lambda p: p.get("sentiment", 0.0))
            bear = min(posts, key=lambda p: p.get("sentiment", 0.0))
            if bull.get("sentiment", 0.0) >= 0.4 and sent > 0:
                shout = (f"{bull['handle']} finally someone on this board GETS it "
                         f"(sentiment {bull.get('sentiment', 0):+.1f} \U0001F49B). the rest of "
                         f"you posting fear while we post P&L. crowd {crowd:+.2f}, we move.")
            elif bear.get("sentiment", 0.0) <= -0.4:
                shout = (f"{bear['handle']} habibi you've been bearish since forever — "
                         f"blocked and unblocked you just to see the {bear.get('sentiment', 0):+.1f} "
                         f"sentiment again \U0001F62D the crowd is at {crowd:+.2f}, lighten up.")
        # filler content — keeps the cadence at 4-6 a month
        if shout is None and since >= 4 and day - self._last_filler >= 6:
            pick = day % 3
            if pick == 0 and hot:
                r1m, c, r = hot[0]
                px = r.get("Close")
                px_txt = f" to {px * 1.1:,.0f}" if self._ok(px) else ""
                shout = (f"POLL for the majlis: {names.get(c, c)}{px_txt}?? it's {r1m:+.1%} "
                         f"this month and my comments are 90% rockets. drop a \U0001F406 "
                         f"if you're long, drop excuses if you're not.")
            elif pick == 1:
                shout = (f"portfolio check: SAR {equity:,.0f}. followers: {followers:,}. "
                         f"crowd sentiment {crowd:+.2f}. the brand is ALWAYS liquid "
                         f"\U0001F406✨ link in bio for the watchlist.")
            elif hot:
                r1m, c, _ = hot[0]
                shout = (f"the algo bros are quiet today which means {names.get(c, c)} "
                         f"({r1m:+.1%}/1m) is about to do something. screenshot this. "
                         f"if I'm right it was analysis, if I'm wrong it was satire.")
            else:
                shout = (f"trending page EMPTY, TASI {tret:+.2%}, crowd {crowd:+.2f}. "
                         f"doing a Q&A instead: yes the \U0001F406 is real, no I won't "
                         f"share my exact entries, yes SAR {equity:,.0f} is real. next.")
            self._last_filler = day
        if shout:
            self._last_shout = day
        return shout


STRATEGY = Lulu()
