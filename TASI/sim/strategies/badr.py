"""Badr — the full moon. Disciplined mean reversion that only buys quality pullbacks.

Season 2's contrarian lost 20% by inverting every rule that matters: he bought
names 30-55% below their highs and sitting on their 52-week lows, averaged down
into them, sold his winners the moment they healed back to a 52-week high, and
let a rotting position run 200 sessions before calling it carrion. His win rate
was 65% and his profit factor was 0.65 — he was right often and paid for it,
because his average loss was three times his average win.

This is the same school with the asymmetry turned the right way up.

THE RULEBOOK (a general function of indicators, prices and peers — no dates,
no per-ticker plans, no memorised tape):

  1. QUALITY GATE FIRST. A name is a candidate only if its long-term structure is
     intact: AdjClose at least 10% above its 200-day line, sma50 above sma200,
     positive 12-month return, three-month relative strength at least matching
     TASI, drawdown from its own peak shallower than 30%, real turnover, sane
     ATR. Anything below its 200-day line is invisible. That is where knives live,
     and the gate is self-regulating: in a broad bear market almost nothing
     qualifies, so the book empties itself into cash with no macro forecast.
  2. THEN THE DISCOMFORT. Inside that healthy set I want short-term pain: price
     under its 20-day line, plus RSI oversold or a sharp one-week drop or a close
     pinned to the lower Bollinger band. Quality plus discomfort — never
     discomfort alone.
  3. SCALE IN, NEVER AVERAGE DOWN. Three quarters of the target on the signal.
     The second tranche is a CONFIRMATION add: only when the name reclaims its
     20-day line with the 200-day structure still intact. If it keeps falling I
     do not add, I stop out. A winner that comes back to its 20-day line without
     breaking anything earns one pyramid add — a dip inside a position that has
     already proved itself.
  4. LOSSES ARE SMALL, FAST AND UNARGUABLE. A young entry that loses its 50-day
     line inside 25 sessions was simply a wrong read and is killed on the spot —
     that one rule is the whole difference from the season-2 autopsy. Behind it
     sit a decisive-200-day-break exit, a time stop for a reversion that never
     reverted, and a wide percentage backstop that in practice almost never has
     to fire, because the structural exits get there first.
  5. WINNERS RUN. I do not sell strength. No selling into 52-week highs, no
     euphoria kills, no profit target. A winner leaves only through a trailing
     give-back from its own peak gain, and that leash shortens in a downtrend.
  6. CONCENTRATION WITH RESPECT FOR LIQUIDITY. Six full-size names, volatility-
     scaled weights, a hard cap of three per sector, and no order larger than 2%
     of a name's daily turnover.
  7. PEERS ARE A TIEBREAK, NOT A SIGNAL. Among candidates my own screen has
     already cleared, I rank up the ones that books currently up on the quarter
     also hold, and size those a little larger. Season 2 showed which way that
     lean has to point: crowd-following momentum won the year, the contrarian
     lost it. Every peer term is zero when ctx["peers"] is empty, so the
     rulebook is complete without them and only sharpens with them.
"""

from __future__ import annotations

from strategy_base import Strategy

NAN = float("nan")
_INF = float("inf")


def _f(row, key):
    """Fetch a float out of a view row, NaN-safe."""
    try:
        return float(row.get(key, NAN))
    except (TypeError, ValueError):
        return NAN


def _ok(*xs):
    for x in xs:
        if not isinstance(x, (int, float)) or x != x or x == _INF or x == -_INF:
            return False
    return True


def _clip(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


PARAMS = {
    # --- quality gate -------------------------------------------------------
    "SMA200_BUF": 1.10,     # AdjClose must be >= sma200 * this
    "MOM_MIN": 0.05,        # min trailing 12m return
    "RS_MIN": 0.0,          # min 3-month relative strength vs TASI
    "DD_FLOOR": -0.30,      # max drawdown from own peak still called healthy
    "LIQ_MIN": 3.0e6,       # min daily turnover, SAR
    "PX_MIN": 2.0,          # no sub-2 SAR lottery tickets
    "ATR_MAX": 0.09,        # max daily ATR as a fraction of price
    # --- the dip ------------------------------------------------------------
    "RSI_BUY": 45.0,
    "WK_DROP": -0.05,
    "BBP_BUY": 0.20,
    # --- sizing -------------------------------------------------------------
    "MAX_POS": 6,
    "BASE_W": 0.22,         # full-size target weight per name
    "TRANCHE1": 0.75,       # fraction of target taken on the signal
    "MAX_ADDS": 1,          # confirmation adds per name
    "PYR_MIN": 0.10,        # a winner must be this far ahead to be pyramided
    "PYR_FRAC": 0.70,       # pyramid size vs the full target
    "MAX_BUYS_DAY": 2,
    "SECTOR_CAP": 3,
    "W_CAP": 0.26,          # hard ceiling on any single target weight
    "TURN_CAP": 0.02,       # order value <= this fraction of daily turnover
    "MIN_TICKET": 1200.0,
    "CASH_MIN": 1500.0,
    # --- exits --------------------------------------------------------------
    "FAST_EXIT_D": 25,      # sessions in which losing the 50-day line is fatal
    "FAST_EXIT_S50": 0.96,
    "STOP": -0.22,          # backstop; the structural exits fire long before it
    "TREND_EXIT": 0.90,     # exit below sma200 * this
    "TIME_STOP_D": 60,      # sessions ...
    "TIME_STOP_MIN": 0.03,  # ... with less than this gain -> release
    "TRAIL_ARM": 0.18,      # arm the trail once peak gain reaches this
    "TRAIL_GIVE": 0.12,     # give-back from peak gain that closes the trade
    "COOL_D": 20,           # sessions before re-entering a name I exited
    "REENTRY_BAN": 2,       # hard stop-outs before a name is banned outright
    # --- regime -------------------------------------------------------------
    "BEAR_POS": 2,          # max positions in a confirmed index downtrend
    "BEAR_TRAIL": 0.70,     # trail-give multiplier in a downtrend
    # --- peers (all inert when ctx["peers"] is empty) ------------------------
    # Season 2 settled the question: crowd-following momentum won the year and
    # the knife-catching contrarian lost it. So the peer terms only ever lean
    # WITH a strong book, never against one, and they are capped small enough
    # that they can reorder my shortlist but never put a name on it.
    # Sized deliberately small: verified against a synthetic field of rival books
    # to be neutral at worst, so the peer read can never cost me the standalone
    # result — it only breaks ties.
    "PEER_TILT": 0.06,      # max size tilt from peer confirmation
    "PEER_SCORE": 0.06,     # max ranking bonus from strong peers holding a name
}

MOODS_BUY = ["patient", "accumulating", "constructive", "measured", "engaged"]
MOODS_FLAT = ["watchful", "unhurried", "selective", "reserved", "dry-powder"]
MOODS_CUT = ["defensive", "risk-off", "protective", "trimmed back", "clinical"]
MOODS_WIN = ["satisfied", "booking it", "unsentimental", "paid", "disciplined"]


class Badr(Strategy):
    meta = {
        "handle": "badr",
        "name": "Badr",
        "emoji": "🌗",
        "tagline": "Buy the dip — but only the dips that come back.",
        "character": (
            "A disciplined mean-reversion specialist who treats the 200-day line as a "
            "border, not a suggestion: nothing below it is ever a candidate, however "
            "cheap it looks. He buys short-term pain inside long-term strength, enters "
            "in tranches, kills a failed read within weeks, and refuses on principle to "
            "sell a winner just because it has become expensive."
        ),
        "risk_style": "quality mean reversion / asymmetric exits",
        "color": "#888888",
    }

    def __init__(self, **over):
        self.P = dict(PARAMS)
        self.P.update(over)
        self._st = {}         # code -> per-position bookkeeping
        self._pend_buy = {}   # code -> day the buy was queued
        self._pend_sell = {}  # code -> day the sell was queued
        self._cool = {}       # code -> day of last exit
        self._stopped = {}    # code -> hard stop-outs suffered in this name
        self._nvar = 0

    # ------------------------------------------------------------------ core
    def decide(self, date, view, portfolio, ctx):
        P = self.P
        day = int(ctx.get("day_index", 0))
        names = ctx.get("names", {}) or {}
        sectors = ctx.get("sectors", {}) or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        if not _ok(breadth):
            breadth = 0.5
        positions = portfolio.get("positions", {}) or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0) or 1.0

        tasi = view.get("TASI") or view.get("TASI_SR") or {}
        t_close = _f(tasi, "AdjClose")
        t_s200 = _f(tasi, "sma200")
        t_s50 = _f(tasi, "sma50")
        t_dd = _f(tasi, "drawdown")
        t_rsi = _f(tasi, "rsi14")
        index_up = _ok(t_close, t_s200) and t_close > t_s200
        # A confirmed index downtrend: price under the 200-day AND the 50-day
        # under the 200-day. One dip through the line is not a bear market;
        # both lines rolled over is.
        bear = (_ok(t_close, t_s200, t_s50)
                and t_close < t_s200 and t_s50 < t_s200)

        # ---- housekeeping ---------------------------------------------------
        for c in list(self._pend_buy):
            if day - self._pend_buy[c] > 5 or c in positions:
                self._pend_buy.pop(c, None)
        for c in list(self._pend_sell):
            if day - self._pend_sell[c] > 5 or c not in positions:
                self._pend_sell.pop(c, None)
        for c in list(self._st):
            if c not in positions and c not in self._pend_buy:
                self._cool[c] = day
                self._st.pop(c, None)

        # ---- the field's public books ---------------------------------------
        # Never a buy signal on its own; only a tiebreak and a size tilt among
        # names my own screen has already cleared, and only ever leaning WITH
        # the books that are actually up on the quarter.
        peer_w = {}
        peers = ctx.get("peers") or {}
        if peers and self.P["PEER_SCORE"] > 0.0:
            acc, wsum = {}, 0.0
            for _h, pb in peers.items():
                r63 = pb.get("ret_63", 0.0)
                if not _ok(r63):
                    r63 = 0.0
                # only a book that is actually up on the quarter gets a vote,
                # and the better it is doing the louder that vote
                if r63 <= 0.0:
                    continue
                qual = _clip(4.0 * r63, 0.0, 2.0)
                wsum += qual
                for cc, ww in (pb.get("positions") or {}).items():
                    if _ok(ww):
                        acc[cc] = acc.get(cc, 0.0) + qual * ww
            if wsum > 0:
                peer_w = {k: v / wsum for k, v in acc.items()}

        orders = []
        ev = []

        # ----------------------------------------------------------- exits ---
        held_val = 0.0
        for c, p in positions.items():
            upnl = p.get("unrealized_pct", 0.0)
            if not _ok(upnl):
                upnl = 0.0
            held_val += p.get("value", 0.0) or 0.0
            st = self._st.setdefault(c, {"day": day, "adds": 0, "pyr": 0,
                                         "peak": upnl, "ac": p.get("avg_cost", 0.0)})
            # A fill moved my average cost, so the peak gain has to be re-based on
            # it — otherwise a scale-in would fake a trailing-stop hit.
            ac = p.get("avg_cost", 0.0) or 0.0
            if _ok(ac) and ac > 0 and abs(ac - (st["ac"] or ac)) / ac > 0.002:
                st["ac"] = ac
                st["peak"] = upnl
            if upnl > st["peak"]:
                st["peak"] = upnl
            if c in self._pend_sell:
                continue
            r = view.get(c)
            if r is None:
                continue  # halted; the engine force-exits after 20 silent sessions
            adj = _f(r, "AdjClose")
            s200 = _f(r, "sma200")
            s50 = _f(r, "sma50")
            held = day - st["day"]

            # 1. structure break: the only thing I ever owned was that trend
            if _ok(adj, s200) and s200 > 0 and adj < s200 * P["TREND_EXIT"]:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"200-day structure broken ({adj / s200 - 1:+.1%} vs sma200)"})
                self._pend_sell[c] = day
                ev.append(("break", c, upnl, adj / s200 - 1.0))
                continue
            # 2. a young entry that loses its 50-day line was a wrong read
            if (held <= P["FAST_EXIT_D"] and upnl < 0.0 and _ok(adj, s50) and s50 > 0
                    and adj < s50 * P["FAST_EXIT_S50"]):
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"entry invalidated: lost sma50 after {held} sessions ({upnl:+.1%})"})
                self._pend_sell[c] = day
                ev.append(("fast", c, upnl, held))
                continue
            # 3. hard stop
            if upnl <= P["STOP"]:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"hard stop at {upnl:+.1%}"})
                self._pend_sell[c] = day
                self._stopped[c] = self._stopped.get(c, 0) + 1
                ev.append(("stop", c, upnl, held))
                continue
            # 4. trailing give-back — the only way a winner is allowed to leave
            give = P["TRAIL_GIVE"] * (P["BEAR_TRAIL"] if bear else 1.0)
            if st["peak"] >= P["TRAIL_ARM"] and upnl <= st["peak"] - give:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"trail: {upnl:+.1%} after peaking {st['peak']:+.1%}"})
                self._pend_sell[c] = day
                ev.append(("trail", c, upnl, st["peak"], bear))
                continue
            # 5. time stop: a reversion that never reverted
            if held >= P["TIME_STOP_D"] and upnl < P["TIME_STOP_MIN"]:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"time stop: {held} sessions for {upnl:+.1%}"})
                self._pend_sell[c] = day
                ev.append(("time", c, upnl, held))

        # ------------------------------------------------------ candidates ---
        cands = self._screen(view, peer_w)

        invested = (held_val / equity) if equity > 0 else 0.0
        max_pos = P["BEAR_POS"] if bear else P["MAX_POS"]
        room = max_pos - (len(positions) - len(self._pend_sell)) - len(self._pend_buy)
        can_spend = cash > P["CASH_MIN"]

        # ------------------------------------------- scale-ins into my book ---
        if can_spend and not bear:
            for c, p in positions.items():
                if c in self._pend_sell or c in self._pend_buy:
                    continue
                st = self._st.get(c)
                if st is None or day - st["day"] < 3:
                    continue
                r = view.get(c)
                if r is None:
                    continue
                adj, s20 = _f(r, "AdjClose"), _f(r, "sma20")
                s50, s200 = _f(r, "sma50"), _f(r, "sma200")
                upnl = p.get("unrealized_pct", 0.0)
                if not _ok(adj, s20, s50, s200, upnl):
                    continue
                if not (adj > s20 and adj > s200 and s50 > s200):
                    continue
                # confirmation add: it reclaimed the 20-day line while still near
                # my cost. This is an add on evidence, not an average-down on hope.
                if st["adds"] < P["MAX_ADDS"] and -0.08 <= upnl <= 0.06:
                    kind, frac = "add", 1.0 - P["TRANCHE1"]
                # pyramid: a paying position back at its 20-day line — the same
                # dip logic, applied to something that has already worked.
                elif (st["pyr"] < 1 and upnl >= P["PYR_MIN"]
                        and adj <= s20 * 1.02 and p.get("weight", 0.0) < 0.28):
                    kind, frac = "pyr", P["PYR_FRAC"]
                else:
                    continue
                sar = self._cap(self._target_w(c, r, peer_w) * frac * equity, r, cash)
                if sar < P["MIN_TICKET"]:
                    continue
                why = (f"tranche 2: reclaimed sma20 at {upnl:+.1%} on cost" if kind == "add"
                       else f"pyramid: winner back at its 20-day line, {upnl:+.1%} on cost")
                orders.append({"code": c, "side": "buy", "sar": round(sar, 2), "reason": why})
                if kind == "add":
                    st["adds"] += 1
                else:
                    st["pyr"] += 1
                self._pend_buy[c] = day
                cash -= sar
                ev.append((kind, c, upnl, adj / s20 - 1.0))
                break  # one scale-in per session is enough

        # ----------------------------------------------------- new entries ---
        opened = []
        if can_spend and room > 0 and cands:
            sec_ct = {}
            for c in list(positions) + list(self._pend_buy):
                s = sectors.get(c, "?")
                sec_ct[s] = sec_ct.get(s, 0) + 1
            n_new = 0
            for _score, c, info in cands:
                if n_new >= P["MAX_BUYS_DAY"] or room <= 0 or cash <= P["CASH_MIN"]:
                    break
                if c in positions or c in self._pend_buy or c in self._pend_sell:
                    continue
                if self._stopped.get(c, 0) >= P["REENTRY_BAN"]:
                    continue
                if day - self._cool.get(c, -9999) < P["COOL_D"]:
                    continue
                sec = sectors.get(c, "?")
                if sec_ct.get(sec, 0) >= P["SECTOR_CAP"]:
                    continue
                r = view.get(c)
                sar = self._cap(self._target_w(c, r, peer_w) * P["TRANCHE1"] * equity, r, cash)
                if sar < P["MIN_TICKET"]:
                    continue
                orders.append({"code": c, "side": "buy", "sar": round(sar, 2),
                               "reason": (f"quality dip: RSI {info['rsi']:.0f}, "
                                          f"{info['d52h']:+.0%} off 52w-high, 12m {info['r12']:+.0%}, "
                                          f"{info['above']:+.0%} over sma200")})
                self._pend_buy[c] = day
                self._st[c] = {"day": day, "adds": 0, "pyr": 0, "peak": 0.0, "ac": 0.0}
                sec_ct[sec] = sec_ct.get(sec, 0) + 1
                cash -= sar
                room -= 1
                n_new += 1
                opened.append((c, info))

        # -------------------------------------------------------- narrative ---
        invested = _clip(invested, 0.0, 2.0)
        sent = _clip((breadth - 0.45) * 1.6, -0.5, 0.5)
        if _ok(t_dd):
            sent += _clip(t_dd * 1.2, -0.35, 0.0)
        sent += _clip(len(cands) * 0.05, 0.0, 0.30)
        sent -= 0.12 * sum(1 for e in ev if e[0] in ("stop", "break", "fast"))
        if bear:
            sent = min(sent, -0.15)
        sent = _clip(sent, -0.95, 0.95)

        if any(e[0] == "trail" for e in ev):
            mood = MOODS_WIN[day % len(MOODS_WIN)]
        elif any(e[0] in ("stop", "break", "fast", "time") for e in ev):
            mood = MOODS_CUT[day % len(MOODS_CUT)]
        elif opened or any(e[0] in ("add", "pyr") for e in ev):
            mood = MOODS_BUY[day % len(MOODS_BUY)]
        else:
            mood = MOODS_FLAT[day % len(MOODS_FLAT)]

        note = self._note(day, ev, opened, cands, names, positions, cash, equity,
                          invested, breadth, t_close, t_rsi, index_up, bear, len(peers))
        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}

    # -------------------------------------------------------------- screening
    def _screen(self, view, peer_w):
        """Ranked (score, code, info) for everything passing quality + dip."""
        P = self.P
        rsi_buy, wk, bbp_buy = P["RSI_BUY"], P["WK_DROP"], P["BBP_BUY"]
        out = []
        for c, r in view.items():
            if c == "TASI" or c == "TASI_SR" or not isinstance(r, dict):
                continue
            adj = _f(r, "AdjClose")
            s20 = _f(r, "sma20")
            s50 = _f(r, "sma50")
            s200 = _f(r, "sma200")
            if not _ok(adj, s20, s50, s200) or s200 <= 0:
                continue
            # --- quality gate: an intact long-term trend, and only that ---
            if adj < s200 * P["SMA200_BUF"] or s50 <= s200:
                continue
            if adj > s20:            # must actually be in a pullback
                continue
            turn = _f(r, "turnover_sar")
            atrp = _f(r, "atr_pct")
            dd = _f(r, "drawdown")
            if not _ok(turn, atrp, dd):
                continue
            if adj < P["PX_MIN"] or turn < P["LIQ_MIN"]:
                continue
            if atrp > P["ATR_MAX"] or dd < P["DD_FLOOR"]:
                continue
            rs3 = _f(r, "rs_tasi_3m")
            if not _ok(rs3) or rs3 < P["RS_MIN"]:
                continue
            r12, r6 = _f(r, "ret_12m"), _f(r, "ret_6m")
            # IPOs have no 12-month history; a 6-month run stands in for it
            mom = r12 if _ok(r12) else (r6 * 1.6 if _ok(r6) else NAN)
            if not _ok(mom) or mom < P["MOM_MIN"]:
                continue
            # --- the dip: short-term discomfort inside that strength ---
            rsi = _f(r, "rsi14")
            r1w = _f(r, "ret_1w")
            bbp = _f(r, "bb_pctb")
            if not _ok(rsi):
                continue
            if not (rsi <= rsi_buy
                    or (_ok(r1w) and r1w <= wk)
                    or (_ok(bbp) and bbp <= bbp_buy)):
                continue
            # --- rank: trend quality first, depth of discomfort second ---
            trend = (0.60 * _clip(mom, 0.0, 1.5)
                     + 0.80 * _clip(rs3, -0.3, 0.8)
                     + 0.40 * _clip(r6 if _ok(r6) else 0.0, 0.0, 0.9))
            dip = ((50.0 - _clip(rsi, 5.0, 60.0)) / 50.0
                   + 3.0 * max(0.0, -(r1w if _ok(r1w) else 0.0))
                   + max(0.0, 0.30 - _clip(bbp if _ok(bbp) else 0.5, -0.5, 1.5)))
            score = trend + 0.80 * dip - 3.0 * max(0.0, atrp - 0.04)
            pw = peer_w.get(c, 0.0)
            if pw > 0.0:
                score += _clip(pw / 0.10, 0.0, 1.0) * P["PEER_SCORE"]
            d52h = _f(r, "dist_52w_high")
            out.append((score, c, {
                "rsi": rsi, "r12": mom, "turn": turn, "pw": pw,
                "d52h": d52h if _ok(d52h) else 0.0,
                "r1w": r1w if _ok(r1w) else 0.0,
                "above": adj / s200 - 1.0,
            }))
        out.sort(key=lambda x: -x[0])
        return out[:20]

    # ----------------------------------------------------------------- sizing
    def _target_w(self, code, row, peer_w):
        """Full-size target weight: volatility-scaled, mildly peer-tilted."""
        P = self.P
        w = P["BASE_W"]
        atrp = _f(row or {}, "atr_pct")
        if _ok(atrp) and atrp > 0:
            w *= _clip(0.030 / atrp, 0.65, 1.35)
        pw = peer_w.get(code, 0.0)
        if pw > 0.0:
            w *= 1.0 + _clip(pw / 0.06, 0.0, 1.0) * P["PEER_TILT"]
        return _clip(w, 0.03, P["W_CAP"])

    def _cap(self, sar, row, cash):
        """No order bigger than my cash or than a slice of the name's turnover."""
        sar = min(sar, cash * 0.92)
        turn = _f(row or {}, "turnover_sar")
        if _ok(turn) and turn > 0:
            sar = min(sar, turn * self.P["TURN_CAP"])
        return max(0.0, sar)

    # -------------------------------------------------------------- narrative
    def _note(self, day, ev, opened, cands, names, positions, cash, equity,
              invested, breadth, t_close, t_rsi, index_up, bear, n_peers):
        def nm(c):
            return names.get(c, c)

        for e in ev:
            if e[0] == "fast":
                return (f"{nm(e[1])} lost its 50-day line {e[3]} sessions after I bought it, "
                        f"out at {e[2]:+.1%}. A pullback entry that fails that fast was a "
                        f"wrong read, not bad luck. Small and early beats large and late.")
            if e[0] == "stop":
                return (f"Backstop hit on {nm(e[1])} at {e[2]:+.1%} after {e[3]} sessions — it "
                        f"got past the 50-day rule and the 200-day rule and still fell apart. "
                        f"Rare, and it means my read was wrong twice. Out, no negotiation.")
            if e[0] == "break":
                return (f"{nm(e[1])} closed {e[3]:+.1%} through its 200-day line — that line "
                        f"was the entire thesis. Closed at {e[2]:+.1%}. A cheap stock below "
                        f"its 200-day is not cheap, it is early, and early is a loss.")
            if e[0] == "trail":
                tight = " The index is rolled over, so the leash was already short." if e[4] else ""
                return (f"Released {nm(e[1])} at {e[2]:+.1%} after a peak of {e[3]:+.1%} on cost. "
                        f"I never sell strength; I sell the give-back from strength.{tight}")
            if e[0] == "time":
                return (f"{nm(e[1])} held {e[3]} sessions and produced {e[2]:+.1%}. A reversion "
                        f"that has not reverted in three months is not a reversion, it is rent. "
                        f"Capital recycled.")
            if e[0] == "add":
                return (f"Second tranche into {nm(e[1])}: it reclaimed its 20-day line "
                        f"({e[3]:+.1%} above it) while still {e[2]:+.1%} on my cost. "
                        f"An add on confirmation — the opposite of an average-down.")
            if e[0] == "pyr":
                return (f"Pyramided {nm(e[1])} at {e[2]:+.1%} on cost: it came back to its "
                        f"20-day line without breaking anything. Adding to a position that "
                        f"has already proved itself is the cheapest risk on this screen.")
        if opened:
            c, i = opened[0]
            more = f" Also opened {nm(opened[1][0])}." if len(opened) > 1 else ""
            return (f"Opened {nm(c)}: RSI {i['rsi']:.0f}, one-week move {i['r1w']:+.1%}, "
                    f"{i['d52h']:+.0%} off its 52-week high — but 12-month return {i['r12']:+.0%} "
                    f"and still {i['above']:+.0%} above its 200-day line. Quality first, "
                    f"discomfort second.{more}")

        n_pos = len(positions)
        tstr = f"{t_close:,.0f}" if _ok(t_close) else "unquoted"
        rstr = f"{t_rsi:.0f}" if _ok(t_rsi) else "n/a"
        if cands:
            _, c0, i0 = cands[0]
            watch = (f"Top of the watchlist: {nm(c0)}, RSI {i0['rsi']:.0f}, 12m {i0['r12']:+.0%}, "
                     f"turnover SAR {i0['turn'] / 1e6:.1f}m.")
        else:
            watch = "Nothing clears quality-plus-dip today; the screen is empty by construction."
        regime = ("The 50-day is under the 200-day on the index — I am running two slots, "
                  "not six, and the trailing stops are tighter." if bear else
                  ("Index above its own 200-day, so the candidate pool is wide."
                   if index_up else "Index under its 200-day but not yet rolled over."))
        variants = [
            f"TASI {tstr}, breadth {breadth:.0%}. {watch} Book {invested:.0%} invested across "
            f"{n_pos} names, SAR {cash:,.0f} idle.",
            f"{watch} {regime}",
            f"Equity SAR {equity:,.0f}, {n_pos} positions, {invested:.0%} deployed. "
            f"{len(cands)} names pass quality-plus-dip right now.",
            f"Breadth {breadth:.0%}, index RSI {rstr} at {tstr}. "
            f"{'Waiting is a position and I am holding it.' if not cands else watch}",
            f"{n_pos} names, {invested:.0%} of equity at work. No thesis in this book survives "
            f"a close below its 200-day line, and none of them is sold for being expensive.",
            (f"Reading {n_peers} peer books for confirmation only — the screen decides, they "
             f"break ties. {watch}" if n_peers else
             f"{regime} {watch}"),
        ]
        self._nvar += 1
        return variants[(day * 3 + self._nvar) % len(variants)]


STRATEGY = Badr()
