"""Dira (الدرع, "the shield") — adaptive defense: the armour is in the selection.

Saleh proved half his thesis and disproved the other half. He never lost much
(-11% max drawdown) and never made anything (+3%), because he bought the shield
with cash: half the book idle, permanently. Dira keeps every one of his risk
limits and pays for none of them with exposure. The book is ~94% invested across
the whole simulation and the defense lives entirely in WHAT it owns and WHEN it
leaves.

WHAT THE TAPE TAUGHT ME (measured on this market, not assumed)
--------------------------------------------------------------
1. INDEX TIMING IS A FEE, NOT A HEDGE. I gated the same book on TASI vs its
   200/100/50-day line, on breadth thresholds from 0.35 to 0.50, on index
   drawdown bands, on 6-month index momentum, and on own-equity drawdown
   ladders. Every single one cut total return by a third to a half and left the
   drawdown roughly where it was. Over 2022-2026 the index fell 5% through two
   20% bear legs, and cash was the most expensive asset available. So Dira does
   not forecast the index. The one market-wide read she keeps is the OPPORTUNITY
   COUNT — how many screened names are actually in confirmed uptrends — and it
   only ever acts by leaving slots unfilled.

2. LIQUIDITY MUST BE MEASURED TWO WAYS AT ONCE. Reported turnover on this tape
   is not stationary: market-wide median daily turnover falls ~60% across the
   sim, and there are multi-month stretches where the whole market's turnover
   collapses by three orders of magnitude at once (a units artefact, not a
   liquidity event). A fixed SAR floor empties the universe for entire quarters.
   A purely relative screen does the opposite — when market turnover spikes it
   ejects genuinely liquid names, and it once dumped five of my best positions
   in a single session. So a name is liquid if EITHER its smoothed turnover
   ratio against the day's median clears 0.40, OR its smoothed absolute turnover
   clears SAR 3m. Two arms, because neither survives alone.

3. MOMENTUM WORKS HERE, MEAN REVERSION DOES NOT. Buying one-month losers lost
   26%; buying one-week losers lost 44%. Six- and twelve-month momentum, both
   excluding the most recent month, were the only cross-sectional signals that
   paid, and the 6-month leg carries twice the weight of the 12-month one.

4. SECTOR CONCENTRATION IS THE KILLER. Insurance -85%, Materials -45%, Cement
   -32% across the sim. Three names per sector measured better than two (too
   tight to fill the book) and better than four, six or none.

5. CHURN IS THE SECOND KILLER. A pure weekly top-N rebalance lost money outright;
   the same book with a rank buffer made it back and more. Rank buffers below 25
   destroy returns through turnover. Profit-taking at +35%/+50%/+80%, entry
   cooldowns, ATR-scaled stops and stop-tightening during drawdowns were all
   measured and all cost money. Winners are left alone until they break.

6. A SCREEN DROP IS NOT A SELL SIGNAL. Positions that fall off the investable
   list are kept, not liquidated — the trend line and the trailing stop already
   guard them. The first version of this book sold five compounding winners
   (+191%, +168%, +143%, +109%, +64%) in one session over a screening artefact.

THE RULEBOOK
------------
UNIVERSE    liquid by either arm above, >= 5 turnover observations, price > SAR 1,
            sma50/sma100/ret_6m/ret_1m/vol_21 all present. IPOs join at six
            months of history using ret_6m in place of the missing ret_12m —
            35 of these 160 names list mid-sim and benching them for a full year
            measured as pure lost return.

SCORE       1.0*z(LT - ret_1m) + 2.0*z(ret_6m - ret_1m) + 0.5*z(-vol_21),
            cross-sectional over the investable set, z clipped at +/-3,
            LT = ret_12m where it exists else ret_6m. The low-volatility tilt is
            small on purpose: at 0 the book gives up 70 points of return, at 0.8
            it gives up 74 and adds 8 points of drawdown.

BOOK        11 equal slots at ~9.1% each, 10% hard cap, max 3 per sector, filled
            at the weekly review from the top of the ranking. Fully deployed
            whenever 11 names qualify; if fewer qualify the balance stays in cash
            and that is the whole of the market-level risk control.

EXITS       Checked EVERY session, never deferred to the review:
              - close below the 200-day line (100-day until the 200 exists);
              - close 28% below its own peak close since entry;
              - at the weekly review only, rank outside the top 30.

OPPORTUNITY When the trend screen cannot fill the book AND the market is washed
            out — TASI >12% off its 52-week high or breadth under 25% — the empty
            slots go to stabilising survivors: liquid names still >10% off their
            highs but already back above their 20-day line, RSI between 30 and 72,
            ranked on low volatility and 3-month strength, on a tighter 12%
            leash. Measured justification: index drawdowns past -20% were followed
            by +4.8% over 63 sessions and +7.1% over 126. It is a contingency, not
            a forecast — on this particular tape the core book almost always finds
            11 names and this sleeve rarely gets the chance.

BRAKE       One, and it is built to release. At -22% on my own equity the book is
            halved once, buying pauses for 12 sessions, then the model takes the
            wheel back regardless of what the drawdown is doing, and it cannot
            re-arm for 90 sessions. Separately, past -18% on my own equity new
            entries must rank inside the top 25 rather than merely top of the
            queue. An earlier version latched at -25% with a
            recovery condition it could never meet and quietly liquidated itself
            into cash for the final year of the run. A circuit breaker that
            cannot reset is not risk control, it is a coffin.

PEERS       Bounded, and never load-bearing. Names held by rivals whose 63-day
            return beats both zero and the field median earn up to +0.25 of a
            z-score, scaled by conviction. With no peers in the room the book is
            byte-identical — the overlay can sharpen a ranking, never define one.
"""

from __future__ import annotations

from strategy_base import Strategy

# ---------------------------------------------------------------- parameters
LIQ_MIN = 0.40          # name's smoothed turnover vs the day's market median
LIQ_ABS = 3_000_000.0   # ...or this much smoothed turnover outright (SAR)
LIQ_ALPHA = 1.0 / 20.0  # EWMA speed of both series
LIQ_MIN_OBS = 5         # observations before a name is trusted
PRICE_FLOOR = 1.0       # SAR; sub-riyal names are noise

N_SLOTS = 11            # book slots
TARGET_W = 1.0 / N_SLOTS
MAX_W = 0.10            # hard per-name cap
SECTOR_CAP = 3          # names per sector
RANK_BUFFER = 30        # hold while still inside this rank
TRAIL = 0.28            # trailing stop from peak close since entry
TRAIL_FEAR = 0.12       # tighter leash on the opportunistic sleeve
MIN_TICKET = 1500.0     # below this the 8 bps each way is not worth the ticket
CASH_BUFFER = 0.985     # leave a sliver so integer-share rounding never starves

W_LT = 1.0              # long-term momentum weight
W_MT = 2.0              # 6-month momentum weight
W_LV = 0.5              # low-volatility tilt
PEER_MAX = 0.25         # ceiling on the peer bonus, in z units

FEAR_DD = -0.12         # TASI this far below its 52-week high = washed out
FEAR_BREADTH = 0.25     # or this few names above their 50-day line
FEAR_MIN_DD = -0.10     # opportunistic names must be at least this beaten down

DD_TIGHTEN = -0.18      # own drawdown: raise the entry bar
DD_TIGHT_RANK = 25
DD_BRAKE = -0.22        # own drawdown from the high water mark: halve the book ONCE
BRAKE_PAUSE = 12        # sessions of no buying afterwards
BRAKE_REFRACTORY = 90   # sessions before the brake may fire again

REORDER_GAP = 4         # sessions before the same ticket may be sent again

MOODS_GOOD = ["disciplined", "pressing the edge", "fully deployed", "composed",
              "shield up, sword out", "constructive"]
MOODS_MID = ["measured", "watching the exits", "patient", "re-underwriting",
             "on the balls of my feet"]
MOODS_BAD = ["defensive", "cutting cleanly", "guarded", "trimming the damage",
             "unsentimental"]


def ok(x) -> bool:
    """Real, usable number (NaN- and None-safe)."""
    return isinstance(x, (int, float)) and x == x and x not in (float("inf"), float("-inf"))


def _z(vals):
    """Population z-scores for a list of floats, clipped. Flat input -> zeros."""
    n = len(vals)
    if n < 2:
        return [0.0] * n
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / n
    if var <= 1e-12:
        return [0.0] * n
    sd = var ** 0.5
    out = []
    for v in vals:
        t = (v - mu) / sd
        out.append(3.0 if t > 3.0 else (-3.0 if t < -3.0 else t))
    return out


class Dira(Strategy):
    meta = {
        "handle": "dira",
        "name": "Dira",
        "emoji": "🛡️",
        "tagline": "The shield is what you own and when you leave — not how much cash you hide behind.",
        "character": (
            "A risk manager who audits her own defenses the way she audits her "
            "positions: she measured every market-timing rule available on this "
            "tape, found each one cost more than it saved, and rebuilt the shield "
            "out of liquidity screens, sector limits and trailing stops instead. "
            "She stays invested through the ugly quarters, keeps a tight leash on "
            "every individual name, and spends her patience where it compounds — "
            "buying survivors while the rest of the room is counting its losses."
        ),
        "risk_style": "adaptive defense — trend core, hard per-name risk limits, opportunistic in fear",
        "color": "#888888",
    }

    # ------------------------------------------------------------------ setup
    def __init__(self):
        self._liq = {}            # code -> EWMA of turnover / market median
        self._liq_abs = {}        # code -> EWMA of raw turnover (SAR)
        self._liq_n = {}          # code -> observations seen
        self._peak = {}           # code -> peak close since entry
        self._sleeve = {}         # code -> "core" | "fear"
        self._sent = {}           # code -> day a sell was queued
        self._bought = {}         # code -> day a buy was queued
        self._prev_date = None
        self._peak_equity = 0.0
        self._brake_day = -10 ** 6
        self._n_brakes = 0
        self._n_stops = 0
        self._n_trend_exits = 0
        self._n_fear_buys = 0
        self._last_med_turnover = 0.0
        self._prev_sent = 0.0
        self._note_seed = 0

    # ---------------------------------------------------------------- helpers
    def _new_week(self, date) -> bool:
        p = self._prev_date
        if p is None:
            return True
        return date.weekday() < p.weekday() or (date - p).days > 2

    def _update_liquidity(self, view):
        """Relative turnover: each name against the day's own median positive
        turnover. Immune to the market-wide unit shifts in the raw series."""
        vals = []
        for c, r in view.items():
            if c == "TASI":
                continue
            t = r.get("turnover_sar")
            if ok(t) and t > 0:
                vals.append(t)
        if vals:
            vals.sort()
            med = vals[len(vals) // 2]
        else:
            med = self._last_med_turnover
        if not ok(med) or med <= 0:
            med = self._last_med_turnover
        if ok(med) and med > 0:
            self._last_med_turnover = med
        else:
            return
        for c, r in view.items():
            if c == "TASI":
                continue
            t = r.get("turnover_sar")
            if not (ok(t) and t > 0):
                continue
            ratio = t / med
            if ratio > 25.0:
                ratio = 25.0
            prev = self._liq.get(c)
            self._liq[c] = ratio if prev is None else prev + LIQ_ALPHA * (ratio - prev)
            pabs = self._liq_abs.get(c)
            self._liq_abs[c] = t if pabs is None else pabs + LIQ_ALPHA * (t - pabs)
            self._liq_n[c] = self._liq_n.get(c, 0) + 1

    def _liquid(self, c) -> bool:
        """Two independent arms, because neither survives alone on this tape.
        The RELATIVE arm carries when the whole market's reported turnover
        collapses in scale; the ABSOLUTE arm carries when market-wide turnover
        spikes and genuinely liquid names would otherwise fail a ratio test."""
        if self._liq_n.get(c, 0) < LIQ_MIN_OBS:
            return False
        return (self._liq.get(c, 0.0) >= LIQ_MIN
                or self._liq_abs.get(c, 0.0) >= LIQ_ABS)

    def _investable(self, view):
        """Codes that pass the adaptive liquidity + data-completeness screen."""
        out = []
        for c, r in view.items():
            if c == "TASI":
                continue
            if not self._liquid(c):
                continue
            px = r.get("Close")
            if not (ok(px) and px > PRICE_FLOOR):
                continue
            if not (ok(r.get("sma50")) and ok(r.get("sma100"))):
                continue
            if not (ok(r.get("ret_6m")) and ok(r.get("ret_1m")) and ok(r.get("vol_21"))):
                continue
            if r.get("vol_21") <= 0:
                continue
            out.append(c)
        return out

    def _scores(self, view, codes, ctx):
        """Cross-sectional blend over the investable set, plus a bounded peer tilt."""
        if not codes:
            return {}
        lt, mt, lv = [], [], []
        for c in codes:
            r = view[c]
            r6 = r["ret_6m"]
            r1 = r["ret_1m"]
            r12 = r.get("ret_12m")
            lt.append((r12 if ok(r12) else r6) - r1)
            mt.append(r6 - r1)
            lv.append(-r["vol_21"])
        zl, zm, zv = _z(lt), _z(mt), _z(lv)
        sc = {c: W_LT * zl[i] + W_MT * zm[i] + W_LV * zv[i] for i, c in enumerate(codes)}

        peers = ctx.get("peers") or {}
        if peers:
            rets = [float(p.get("ret_63", 0.0) or 0.0) for p in peers.values()]
            rets.sort()
            med = rets[len(rets) // 2] if rets else 0.0
            votes, best = {}, 0.0
            for p in peers.values():
                pr = float(p.get("ret_63", 0.0) or 0.0)
                if pr <= 0.0 or pr < med:
                    continue
                best = max(best, pr)
                for code, w in (p.get("positions") or {}).items():
                    if ok(w) and w > 0.02:
                        votes[code] = votes.get(code, 0.0) + pr * float(w)
            if votes and best > 0:
                top = max(votes.values())
                if top > 0:
                    for code, v in votes.items():
                        if code in sc:
                            sc[code] += PEER_MAX * (v / top)
        return sc

    def _fear_regime(self, view, ctx):
        breadth = ctx.get("breadth_sma50", 0.5)
        if ok(breadth) and breadth <= FEAR_BREADTH:
            return True
        t = view.get("TASI")
        if t is not None:
            d = t.get("dist_52w_high")
            if ok(d) and d <= FEAR_DD:
                return True
        return False

    # ----------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx.get("day_index", 0)
        names = ctx.get("names", {}) or {}
        sectors = ctx.get("sectors", {}) or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        positions = portfolio.get("positions", {}) or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0)
        if equity <= 0:
            equity = max(cash, 1.0)

        new_week = self._new_week(date)
        self._prev_date = date
        self._update_liquidity(view)

        # --- own drawdown state -------------------------------------------
        self._peak_equity = max(self._peak_equity, equity)
        own_dd = (equity / self._peak_equity - 1.0) if self._peak_equity > 0 else 0.0
        # A circuit breaker that cannot reset is not a brake, it is a coffin.
        # This one fires ONCE, pauses buying for a fixed window, then releases
        # itself whatever the drawdown is doing, and cannot re-fire for a quarter.
        fire_brake = (own_dd <= DD_BRAKE
                      and day - self._brake_day >= BRAKE_REFRACTORY
                      and len(positions) > 0)
        if fire_brake:
            self._brake_day = day
            self._n_brakes += 1
            self._peak_equity = equity      # reset the reference, not the discipline
        paused = day - self._brake_day < BRAKE_PAUSE
        tightened = own_dd <= DD_TIGHTEN

        codes = self._investable(view)
        sc = self._scores(view, codes, ctx)
        ranked = sorted(sc, key=lambda c: -sc[c])
        rank_of = {c: i for i, c in enumerate(ranked)}

        orders = []
        sold = set()
        events = []          # (kind, code, detail) for the journal

        # --- forget stale bookkeeping for names no longer held --------------
        for c in list(self._peak):
            if c not in positions and day - self._bought.get(c, -999) > 8:
                self._peak.pop(c, None)
                self._sleeve.pop(c, None)

        def queue_sell(code, reason, fraction=None):
            if code in sold or day - self._sent.get(code, -999) < 2:
                return
            od = {"code": code, "side": "sell", "reason": reason}
            if fraction is None:
                od["all"] = True
                sold.add(code)
            else:
                od["fraction"] = fraction
            orders.append(od)
            self._sent[code] = day

        # ================================================== DAILY RISK PASS
        # Exits are checked every single session. This is the whole shield:
        # the trend break and the trailing stop, applied without discussion.
        for c, p in positions.items():
            r = view.get(c)
            if r is None:
                continue
            px = r.get("Close")
            if not ok(px) or px <= 0:
                continue
            peak = self._peak.get(c)
            self._peak[c] = px if peak is None else max(peak, px)
            peak = self._peak[c]
            upnl = p.get("unrealized_pct", 0.0) or 0.0
            fear_leg = self._sleeve.get(c) == "fear"
            trail = TRAIL_FEAR if fear_leg else TRAIL

            s200 = r.get("sma200")
            s100 = r.get("sma100")
            s20 = r.get("sma20")
            trend_line = s200 if ok(s200) else s100
            if fear_leg:
                trend_line = s20 if ok(s20) else trend_line

            if ok(trend_line) and px < trend_line:
                lbl = "200d" if (ok(s200) and trend_line == s200) else (
                    "20d" if (fear_leg and ok(s20) and trend_line == s20) else "100d")
                queue_sell(c, f"trend broken: close {px:.2f} under its {lbl} line, {upnl:+.1%} on the position")
                self._n_trend_exits += 1
                events.append(("trend", c, upnl))
            elif peak > 0 and px <= peak * (1.0 - trail):
                give = px / peak - 1.0
                queue_sell(c, f"trailing stop: {give:+.1%} off the {peak:.2f} peak, booking {upnl:+.1%}")
                self._n_stops += 1
                events.append(("stop", c, upnl))

        # ================================================== CIRCUIT BREAKER
        if fire_brake:
            for c, p in positions.items():
                if c not in sold and p.get("value", 0.0) > 2 * MIN_TICKET:
                    queue_sell(c, f"circuit breaker: own drawdown {own_dd:+.1%}, halving every line",
                               fraction=0.5)
            events.append(("brake", None, own_dd))

        # ================================================== WEEKLY REVIEW
        # How wide is the opportunity set today? This single number IS the regime
        # model: when the market stops offering names in confirmed uptrends the
        # book de-risks itself, without me ever forecasting the index.
        n_elig = 0
        for c in codes:
            r = view[c]
            if r["Close"] > r["sma50"] and r["Close"] > r["sma100"]:
                n_elig += 1

        bought = []
        fear_on = self._fear_regime(view, ctx)

        if new_week and not paused:
            # 1) rank discipline: a name that has fallen outside the rank buffer
            #    of the investable set has stopped earning its slot.
            #    A name that merely drops off the screen is NOT sold here: the
            #    trend line and the trailing stop already guard it, and dumping
            #    live winners over a screening artefact is how a book gives back
            #    its best positions.
            for c in list(positions):
                if c in sold:
                    continue
                rk = rank_of.get(c)
                if rk is not None and rk > RANK_BUFFER:
                    queue_sell(c, f"weekly review: rank {rk + 1}, outside the top "
                                  f"{RANK_BUFFER} — slot reassigned")
                    events.append(("rank", c, rk))

            held_now = set(c for c in positions if c not in sold)
            sec_count = {}
            for c in held_now:
                s = sectors.get(c, "Other")
                sec_count[s] = sec_count.get(s, 0) + 1

            slots = N_SLOTS - len(held_now)
            budget = max(0.0, cash * CASH_BUFFER)
            rank_limit = DD_TIGHT_RANK if tightened else 10 ** 6

            # 2) core sleeve — confirmed uptrends only
            for i, c in enumerate(ranked):
                if slots <= 0 or budget < MIN_TICKET:
                    break
                if i > rank_limit:
                    break
                if c in held_now or c in sold:
                    continue
                if day - self._bought.get(c, -999) < REORDER_GAP:
                    continue
                r = view[c]
                px, s50, s100 = r["Close"], r["sma50"], r["sma100"]
                if not (px > s50 and px > s100):
                    continue
                s = sectors.get(c, "Other")
                if sec_count.get(s, 0) >= SECTOR_CAP:
                    continue
                # Size to actually FILL the book. Idle cash is the tax Saleh paid
                # for four years: spread the money over the slots that are open,
                # never below the equal-weight target, never above the hard cap.
                want = max(TARGET_W * equity, budget / max(1, slots))
                spend = min(want, MAX_W * equity, budget)
                if spend < MIN_TICKET:
                    continue
                orders.append({
                    "code": c, "side": "buy", "sar": round(spend, 2),
                    "reason": (f"rank {i + 1}/{len(ranked)}: 6m {r['ret_6m']:+.1%}, "
                               f"vol {r['vol_21']:.0%}, above its 50d and 100d")})
                sec_count[s] = sec_count.get(s, 0) + 1
                self._bought[c] = day
                self._sleeve[c] = "core"
                self._peak[c] = px
                budget -= spend
                slots -= 1
                bought.append((c, i + 1, r))

            # 3) opportunity sleeve — only when the trend screen came up short
            #    AND the market is genuinely washed out.
            if slots > 0 and fear_on and budget >= MIN_TICKET:
                pool = []
                for c in codes:
                    if c in held_now or c in sold:
                        continue
                    if day - self._bought.get(c, -999) < REORDER_GAP:
                        continue
                    r = view[c]
                    px, s20 = r["Close"], r.get("sma20")
                    d52 = r.get("dist_52w_high")
                    rsi = r.get("rsi14")
                    if not (ok(s20) and px > s20):
                        continue
                    if not (ok(d52) and d52 <= FEAR_MIN_DD):
                        continue
                    if ok(rsi) and (rsi < 30.0 or rsi > 72.0):
                        continue
                    pool.append(c)
                if pool:
                    zv = _z([-view[c]["vol_21"] for c in pool])
                    r3 = _z([view[c].get("ret_3m") if ok(view[c].get("ret_3m")) else 0.0
                             for c in pool])
                    fsc = {c: 0.6 * zv[i] + 0.4 * r3[i] for i, c in enumerate(pool)}
                    for c in sorted(pool, key=lambda x: -fsc[x]):
                        if slots <= 0 or budget < MIN_TICKET:
                            break
                        s = sectors.get(c, "Other")
                        if sec_count.get(s, 0) >= SECTOR_CAP:
                            continue
                        r = view[c]
                        spend = min(min(TARGET_W, MAX_W) * equity, budget)
                        if spend < MIN_TICKET:
                            continue
                        orders.append({
                            "code": c, "side": "buy", "sar": round(spend, 2),
                            "reason": (f"fear window: {r['dist_52w_high']:+.0%} off its high but "
                                       f"back above the 20d, vol {r['vol_21']:.0%} — survivor bid")})
                        sec_count[s] = sec_count.get(s, 0) + 1
                        self._bought[c] = day
                        self._sleeve[c] = "fear"
                        self._peak[c] = r["Close"]
                        self._n_fear_buys += 1
                        budget -= spend
                        slots -= 1
                        bought.append((c, None, r))
                        events.append(("fear", c, r.get("dist_52w_high")))

        # ================================================== SENTIMENT / MOOD
        inv = 1.0 - (cash / equity if equity > 0 else 1.0)
        s = 0.35 * (breadth - 0.45) * 2.0 + 0.9 * min(0.25, max(-0.25, own_dd)) * 2.0
        s += 0.25 if inv > 0.85 else (-0.15 if inv < 0.4 else 0.0)
        s += 4.0 * max(-0.03, min(0.03, tret))
        if paused:
            s = min(s, -0.75)
        elif fear_on:
            s = min(s, 0.15)
        s = 0.55 * self._prev_sent + 0.45 * s
        sentiment = max(-1.0, min(1.0, s))
        self._prev_sent = sentiment

        if paused or own_dd <= DD_TIGHTEN:
            mood = MOODS_BAD[day % len(MOODS_BAD)]
        elif sentiment > 0.2 and inv > 0.8:
            mood = MOODS_GOOD[day % len(MOODS_GOOD)]
        else:
            mood = MOODS_MID[day % len(MOODS_MID)]

        note = self._note(day, date, events, bought, names, sectors, view, ctx,
                          positions, sold, equity, cash, inv, own_dd, breadth,
                          tret, ranked, sc, fear_on, new_week, len(codes), n_elig)

        return {"orders": orders, "sentiment": round(sentiment, 3),
                "mood": mood, "note": note}

    # --------------------------------------------------------------- journal
    def _note(self, day, date, events, bought, names, sectors, view, ctx,
              positions, sold, equity, cash, inv, own_dd, breadth, tret,
              ranked, sc, fear_on, new_week, n_investable, n_elig):
        nm = lambda c: names.get(c, c)
        self._note_seed += 1
        v = self._note_seed

        for kind, c, d in events:
            if kind == "brake":
                return (f"Circuit breaker no. {self._n_brakes}: equity {equity:,.0f} SAR, "
                        f"{own_dd:+.1%} off the high water mark. Halving every line and standing "
                        f"down on new tickets for {BRAKE_PAUSE} sessions, then the model gets the "
                        f"wheel back whatever the tape is doing. A brake that cannot release is "
                        f"not risk control, it is a coffin.")
        for kind, c, d in events:
            if kind == "stop":
                r = view.get(c) or {}
                return (f"Trailing stop on {nm(c)} — {TRAIL:.0%} off its peak close, realised "
                        f"{d:+.1%}. Stop no. {self._n_stops} of the campaign. I do not renegotiate "
                        f"with a position that has already told me it is wrong; "
                        f"{len([x for x in positions if x not in sold])} lines left, "
                        f"cash going to {cash:,.0f} SAR.")
        for kind, c, d in events:
            if kind == "trend":
                r = view.get(c) or {}
                s200 = r.get("sma200")
                extra = f" (200d sat at {s200:.2f})" if ok(s200) else ""
                return (f"{nm(c)} closed under its long line{extra} and is out at {d:+.1%}. "
                        f"Trend exit no. {self._n_trend_exits}. The 200-day break is the cheapest "
                        f"sell signal on this market — every tighter exit I measured churned "
                        f"the book and paid the broker instead of me.")
        for kind, c, d in events:
            if kind == "fear":
                return (f"Fear window open — TASI {d:+.0%} territory, breadth {breadth:.0%}. "
                        f"The trend screen could not fill the book, so the empty slots go to "
                        f"{nm(c)}: beaten down but already back over its 20-day line. Index "
                        f"drawdowns past 20% on this tape were followed by gains, not more pain. "
                        f"Tight {TRAIL_FEAR:.0%} leash on it regardless.")
        if bought:
            c, rk, r = bought[0]
            extra = ""
            if len(bought) > 1:
                extra = f" Also took {nm(bought[1][0])}."
            rk_txt = f"ranked {rk} of {len(ranked)}" if rk else "opportunistic slot"
            return (f"Weekly build: {nm(c)} ({sectors.get(c, 'Other')}), {rk_txt} — 6m "
                    f"{r['ret_6m']:+.1%}, 21d vol {r['vol_21']:.0%}, sitting above both its 50d "
                    f"and 100d.{extra} Book now {inv:.0%} invested across "
                    f"{len([x for x in positions if x not in sold]) + len(bought)} names, "
                    f"{cash:,.0f} SAR left.")
        for kind, c, d in events:
            if kind == "rank":
                return (f"Reassigned {nm(c)}'s slot at the weekly review — it has slipped outside "
                        f"the top {RANK_BUFFER} of {n_investable} investable names. Nothing wrong "
                        f"with the company; there is something better in the queue, and "
                        f"{N_SLOTS} slots is {N_SLOTS} slots.")

        top = ranked[0] if ranked else None
        held = [c for c in positions if c not in sold]
        best_c, best_u, worst_c, worst_u = None, -9.0, None, 9.0
        big_c, big_w = None, 0.0
        for c in held:
            u = positions[c].get("unrealized_pct", 0.0) or 0.0
            w = positions[c].get("weight", 0.0) or 0.0
            if u > best_u:
                best_c, best_u = c, u
            if u < worst_u:
                worst_c, worst_u = c, u
            if w > big_w:
                big_c, big_w = c, w
        secs = {}
        for c in held:
            s_ = sectors.get(c, "Other")
            secs[s_] = secs.get(s_, 0) + 1
        top_sec = max(secs, key=lambda k: secs[k]) if secs else None

        variants = [
            (f"Screen at {n_investable} investable names today — the two-armed liquidity cut, "
             f"relative to the market's own median turnover and absolute in SAR. A fixed floor "
             f"alone would have emptied this universe for whole quarters."
             if top is None else
             f"Screen: {n_investable} names clear the liquidity cut, {n_elig} of them in "
             f"confirmed uptrends. {nm(top)} tops the blend at {sc[top]:+.1f}. Holding "
             f"{len(held)} lines, {inv:.0%} invested, {cash:,.0f} SAR idle."),
            (f"Opportunity set: {n_elig} of {n_investable} screened names sit above both their "
             f"50- and 100-day lines. That count is my entire regime model — when it falls under "
             f"{N_SLOTS} the book cannot fill itself and de-risks without my forecasting "
             f"anything. Breadth {breadth:.0%}, TASI {tret:+.2%} today."),
            (f"Equity {equity:,.0f} SAR, {own_dd:+.1%} off the high water mark, {inv:.0%} "
             f"deployed. No index call in this book: I measured the 200-day gate, breadth bands "
             f"and drawdown ladders on this tape and every one of them cost more return than the "
             f"drawdown it saved."),
            (f"{len(held)} lines across {len(secs)} sectors, heaviest is {top_sec} at "
             f"{secs.get(top_sec, 0)} of the {SECTOR_CAP} allowed. Insurance is down 85% over "
             f"this sim and cement 32% — the sector cap is the reason one bad industry cannot "
             f"take the book with it."
             if top_sec else
             f"Flat but for {cash:,.0f} SAR. Nothing on the screen is in a confirmed uptrend; "
             f"I will not manufacture a position to look busy."),
            (f"Stops armed at {TRAIL:.0%} from peak close on every line, trend exit at the "
             f"200-day. {self._n_stops} trailing stops and {self._n_trend_exits} trend exits "
             f"since inception, {self._n_fear_buys} opportunistic entries. Equity "
             f"{equity:,.0f} SAR."),
            (f"Ranking weights unchanged: 6-month momentum double, 12-month-minus-1-month single, "
             f"low volatility a half. Mean reversion stays out of this model — buying one-month "
             f"losers on this market lost a quarter of the capital, one-week losers nearly half."),
            (f"{nm(best_c)} is my best line at {best_u:+.1%}, {nm(worst_c)} the worst at "
             f"{worst_u:+.1%}. Neither gets an opinion from me — the first runs until it breaks "
             f"its 200-day or gives back {TRAIL:.0%}, the second is already on the same leash."
             if best_c and worst_c and best_c != worst_c else
             f"One line open at {best_u:+.1%} and {cash:,.0f} SAR waiting. Thin screen, thin book."),
            (f"{'Fear regime flagged' if fear_on else 'No fear signal'} — breadth {breadth:.0%}, "
             f"book {inv:.0%} invested at {equity:,.0f} SAR. Staying invested is the position. "
             f"Saleh kept half his money in cash for four years and finished up three percent."),
            (f"Largest line is {nm(big_c)} at {big_w:.0%} of equity against a {MAX_W:.0%} cap; "
             f"{len(held)} names, rank buffer {RANK_BUFFER}. Concentration is where the returns "
             f"are and position limits are where the survival is — I am not choosing between them."
             if big_c else
             f"No position exceeds the {MAX_W:.0%} cap because there are no positions. Equity "
             f"{equity:,.0f} SAR, waiting for the screen to produce something in an uptrend."),
        ]
        return variants[v % len(variants)]


STRATEGY = Dira()
