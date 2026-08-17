"""Dr. Muteb — the PhD quant, back from London with a factor model and no patience for vibes.

Disciplined multi-factor long book on the TASI top-50:
  - Cross-sectional 6-1 momentum (ret_6m minus ret_1m) + 3m relative strength vs TASI.
  - Low-volatility tilt: score bonus for low vol_21, inverse-vol position sizing.
  - RSI mean-reversion entry timing: he prefers to buy ranked names on pullbacks
    (RSI 30-45 above the 100d trend) and refuses to chase RSI > 72.
  - Regime overlay: logistic P(bull) from breadth + TASI trend sets gross exposure.
  - Weekly rebalance with a rank buffer (hold to #16, enter from the top 8) to keep
    turnover — "a tax," he says — down. Hard 15% max weight.
  - Hard risk: 2.75x ATR trailing stops checked daily, -15% disaster stop,
    10-session re-entry cooldown after any stop-out.
He speaks in probabilities and z-scores and is mildly exasperated by everyone else.
"""

from __future__ import annotations

import math
from datetime import timedelta

from strategy_base import Strategy

# ---------------------------------------------------------------- parameters
N_TARGET = 8            # target book size
MAX_W = 0.15            # hard max position weight
RANK_BUFFER = 16        # hold while ranked <= this; enter only from top N_TARGET
ENTRY_RSI_MAX = 72.0    # he does not chase statistically overbought names
PULLBACK_LO, PULLBACK_HI = 30.0, 45.0   # mean-reversion entry sweet spot
STOP_ATR_MULT = 2.75    # trailing stop distance in ATRs from peak close
DISASTER_STOP = -0.15   # absolute unrealized-loss stop (ATR-NaN failsafe)
COOLDOWN = 10           # sessions before re-entry after a stop-out
REBAL_BAND = 0.055      # ignore weight gaps smaller than this (turnover tax)
GROSS_HYST = 0.12       # re-aim gross only when the model moves this much
MIN_ORDER = 4000.0      # SAR
MIN_TURNOVER = 2.0e6    # SAR avg daily turnover to enter
VOL_LO, VOL_HI = 0.12, 0.45   # clamp for inverse-vol sizing
W_MOM, W_RS, W_LVOL = 0.40, 0.30, 0.30
SHOUT_GAP = 5           # min sessions between routine shouts
SHOUT_GAP_DRAMA = 3     # min gap when the tape justifies it


def ok(x) -> bool:
    return isinstance(x, (int, float)) and x == x and not math.isinf(x)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def zscores(vals):
    n = len(vals)
    if n < 3:
        return [0.0] * n
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / n
    sd = math.sqrt(var)
    if sd < 1e-9:
        return [0.0] * n
    return [(v - mu) / sd for v in vals]


class DrMuteb(Strategy):
    meta = {
        "handle": "dr_muteb",
        "name": "Dr. Muteb",
        "emoji": "🤓",
        "tagline": "Vibes are not a factor. Momentum, low-vol and stops are.",
        "risk_style": "systematic",
        "color": "#4C78A8",
        "character": (
            "A PhD quant back from London running a disciplined multi-factor book: "
            "6-1 momentum and relative strength, a low-volatility tilt, RSI pullback "
            "entries, inverse-vol sizing under a regime-driven gross target, and "
            "2.75x ATR trailing stops he treats as scripture. Speaks in probabilities "
            "and z-scores; mildly exasperated that the rest of the majlis trades on "
            "feelings and calls it alpha."
        ),
    }

    def __init__(self):
        self.prev_week = None       # (iso_year, iso_week) of last seen session
        self.week_no = 0            # rebalance counter, for journal headers
        self.pos_state = {}         # code -> {"peak": px, "atr0": atr}
        self.cooldown = {}          # code -> day_index of stop-out
        self.stop_issued = {}       # code -> day_index (avoid dupes through halts)
        self.last_shout_day = -99
        self.last_report_month = None
        self.gross_target = 0.65
        self.applied_gross = None   # hysteresis: gross actually used for targets

    # ------------------------------------------------------------------ decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx["names"]
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        cash = portfolio["cash"]
        equity = max(portfolio["equity"], 1.0)
        positions = portfolio["positions"]
        eq_hist = ctx.get("equity_history", [])
        my_ret = (eq_hist[-1] / eq_hist[-2] - 1.0) if len(eq_hist) >= 2 else 0.0

        # --- majlis statistics (he keeps a running eye-roll) ---
        posts = [p for p in ctx.get("majlis", []) if p.get("handle") != "dr_muteb"]
        crowd = (sum(float(p.get("sentiment", 0.0)) for p in posts) / len(posts)
                 if posts else 0.0)

        # --- regime: logistic P(bull) from breadth + TASI trend ---
        t = view.get("TASI")
        above100 = above200 = None
        t3m = 0.0
        z_reg = 1.1 * (breadth - 0.5)
        if t is not None:
            tc = t.get("Close", float("nan"))
            s100, s200 = t.get("sma100", float("nan")), t.get("sma200", float("nan"))
            if ok(tc) and ok(s100):
                above100 = tc > s100
                z_reg += 0.22 if above100 else -0.22
            if ok(tc) and ok(s200):
                above200 = tc > s200
                z_reg += 0.14 if above200 else -0.14
            if ok(t.get("ret_3m", float("nan"))):
                t3m = t["ret_3m"]
                z_reg += clamp(t3m, -0.10, 0.10)
        p_bull = 1.0 / (1.0 + math.exp(-4.0 * z_reg))
        gross = clamp(0.30 + 0.70 * p_bull, 0.30, 0.95)
        self.gross_target = gross

        # --- maintain per-position state; check hard stops daily ---
        orders = []
        stop_events = []   # (code, close, stop_px, unrealized_pct)
        for c in list(self.pos_state):
            if c not in positions:
                self.pos_state.pop(c, None)
        for c, pos in positions.items():
            r = view.get(c)
            if r is None:
                continue                       # halted: stop re-armed on return
            px = r.get("Close", float("nan"))
            if not ok(px) or px <= 0:
                continue
            atr = r.get("atr14", float("nan"))
            st = self.pos_state.setdefault(
                c, {"peak": px, "atr0": atr if ok(atr) else px * 0.02})
            st["peak"] = max(st["peak"], px)
            atr_use = atr if ok(atr) and atr > 0 else st["atr0"]
            stop_px = st["peak"] - STOP_ATR_MULT * atr_use
            recently = day - self.stop_issued.get(c, -99) < 6
            if not recently and (px < stop_px or pos["unrealized_pct"] < DISASTER_STOP):
                orders.append({
                    "code": c, "side": "sell", "all": True,
                    "reason": (f"trailing stop: {px:.2f} < peak {st['peak']:.2f} "
                               f"- {STOP_ATR_MULT}xATR({atr_use:.2f})"),
                })
                self.stop_issued[c] = day
                self.cooldown[c] = day
                stop_events.append((c, px, stop_px, pos["unrealized_pct"]))

        # --- cross-sectional factor scores (cheap; also feeds the journal) ---
        rows = []            # (code, r) passing validity + soft trend gate
        ret6_all = []
        for c, r in view.items():
            if c == "TASI":
                continue
            px = r.get("Close", float("nan"))
            if not (ok(px) and px > 0):
                continue
            if ok(r.get("ret_6m", float("nan"))):
                ret6_all.append(r["ret_6m"])
            needed = ("ret_6m", "ret_1m", "rs_tasi_3m", "vol_21", "rsi14", "sma100")
            if not all(ok(r.get(k, float("nan"))) for k in needed):
                continue
            if px <= 0.97 * r["sma100"]:       # soft trend gate (3% hysteresis)
                continue
            rows.append((c, r))

        # momentum dispersion, for commentary: top-8 minus bottom-8 mean ret_6m
        spread = 0.0
        if len(ret6_all) >= 16:
            srt = sorted(ret6_all)
            spread = (sum(srt[-8:]) / 8 - sum(srt[:8]) / 8) * 100.0

        z_mom = zscores([r["ret_6m"] - r["ret_1m"] for _, r in rows])
        z_rs = zscores([r["rs_tasi_3m"] for _, r in rows])
        z_lv = zscores([-r["vol_21"] for _, r in rows])
        scored = {}
        for i, (c, r) in enumerate(rows):
            s = W_MOM * z_mom[i] + W_RS * z_rs[i] + W_LVOL * z_lv[i]
            rsi = r["rsi14"]
            if PULLBACK_LO <= rsi <= PULLBACK_HI and r["Close"] > r["sma100"]:
                s += 0.35                      # pullback entry bonus
            elif rsi > 68.0:
                s -= 0.25                      # overheated penalty
            scored[c] = s
        ranked = sorted(scored, key=lambda c: (-scored[c], c))
        rank = {c: i + 1 for i, c in enumerate(ranked)}

        # --- weekly rebalance (Sun-Thu week; ISO week shifted by one day) ---
        iso = (date + timedelta(days=1)).isocalendar()
        wk = (iso[0], iso[1])
        rebal = wk != self.prev_week
        self.prev_week = wk

        n_buys = n_exits = 0
        buy_top = exit_info = None
        worst_held = None
        est_vol = None
        if rebal:
            self.week_no += 1
            # gross-target hysteresis: re-aim only on a material regime move
            if self.applied_gross is None or abs(gross - self.applied_gross) >= GROSS_HYST:
                self.applied_gross = gross
            use_gross = self.applied_gross
            stopped_today = {c for c, *_ in stop_events}
            held = [c for c in positions if c not in stopped_today]

            # 1) exits: holdings that fell out of the rank buffer or broke trend
            keep = []
            sells_value = 0.0
            for c in held:
                r = view.get(c)
                if r is None:
                    keep.append(c)             # halted: cannot act, cannot price
                    continue
                if c in scored and rank[c] <= RANK_BUFFER:
                    keep.append(c)
                    if worst_held is None or rank[c] > rank[worst_held]:
                        worst_held = c
                    continue
                why = (f"slipped to factor rank #{rank[c]}/{len(ranked)}"
                       if c in scored else "left the eligible set (trend broken)")
                orders.append({"code": c, "side": "sell", "all": True, "reason": why})
                sells_value += positions[c]["value"]
                self.cooldown[c] = day - COOLDOWN + 4   # short pause, not a stop
                n_exits += 1
                if exit_info is None:
                    exit_info = (c, rank.get(c), positions[c]["unrealized_pct"])

            # 2) entries: top-ranked, entry-grade names to fill the book
            selection = list(keep)
            for c in ranked:
                if len(selection) >= N_TARGET:
                    break
                if c in selection or c in stopped_today:
                    continue
                if rank[c] > N_TARGET:
                    break
                if day - self.cooldown.get(c, -99) < COOLDOWN:
                    continue
                r = view[c]
                if r["rsi14"] > ENTRY_RSI_MAX:
                    continue
                if r["Close"] <= r["sma100"]:
                    continue                   # entries need the full trend gate
                turn = r.get("vol_sma20", float("nan"))
                if not ok(turn) or turn * r["Close"] < MIN_TURNOVER:
                    continue
                selection.append(c)

            # 3) inverse-vol weights under the regime gross target, 15% hard cap
            vols, raw = {}, {}
            for c in selection:
                r = view.get(c)
                v = r["vol_21"] if (r is not None and ok(r.get("vol_21", float("nan")))) \
                    else 0.25
                vols[c] = v
                raw[c] = 1.0 / clamp(v, VOL_LO, VOL_HI)
            tot = sum(raw.values())
            tgt = {}
            if tot > 0:
                tgt = {c: use_gross * raw[c] / tot for c in raw}
                over = sum(max(0.0, w - MAX_W) for w in tgt.values())
                if over > 0:
                    unc = [c for c in tgt if tgt[c] < MAX_W]
                    add = over / len(unc) if unc else 0.0
                    tgt = {c: min(MAX_W, tgt[c] + (add if c in unc else 0.0))
                           for c in tgt}
                wavg = sum(tgt[c] * vols[c] for c in tgt)
                est_vol = wavg * 0.65          # rho ~= 0.3 diversification haircut

            # 4) orders: trims first, then buys by conviction, budget-aware
            budget = cash + sells_value * 0.996 - 0.01 * equity
            for c in selection:
                cur_w = positions.get(c, {}).get("weight", 0.0)
                tw = tgt.get(c, 0.0)
                if cur_w > tw + REBAL_BAND and c in positions:
                    frac = (cur_w - tw) / cur_w
                    orders.append({
                        "code": c, "side": "sell", "fraction": round(frac, 4),
                        "reason": f"trim {cur_w:.1%} -> {tw:.1%} (vol-target)"})
                    budget += frac * positions[c]["value"] * 0.996
            for c in sorted(selection, key=lambda x: (-scored.get(x, -9.0), x)):
                if view.get(c) is None:
                    continue                   # halted: no buys into a dark tape
                cur_w = positions.get(c, {}).get("weight", 0.0)
                tw = tgt.get(c, 0.0)
                gap = (tw - cur_w) * equity
                if tw - cur_w <= REBAL_BAND or gap < MIN_ORDER:
                    continue
                amt = min(gap, budget)
                if amt < MIN_ORDER:
                    continue
                orders.append({
                    "code": c, "side": "buy", "sar": round(amt, 2),
                    "reason": (f"rank #{rank.get(c, 0)}, z={scored.get(c, 0.0):+.2f}, "
                               f"sigma {vols[c]:.0%} -> w {tw:.1%}")})
                budget -= amt * 1.002
                n_buys += 1
                if buy_top is None:
                    buy_top = (c, r)

        # --- mid-week drift control: nothing may breach the 15% cap by much ---
        if not rebal:
            for c, pos in positions.items():
                if pos["weight"] > MAX_W + 0.025 and view.get(c) is not None \
                        and day - self.stop_issued.get(c, -99) >= 6:
                    frac = (pos["weight"] - MAX_W) / pos["weight"]
                    orders.append({
                        "code": c, "side": "sell", "fraction": round(frac, 4),
                        "reason": f"drift {pos['weight']:.1%} > 15% cap"})

        # --- sentiment: the regime model, lightly perturbed by today's tape ---
        sentiment = clamp(1.8 * (p_bull - 0.5) + 2.0 * clamp(tret, -0.05, 0.05),
                          -0.85, 0.85)

        # --- mood ---
        invested = 1.0 - cash / equity
        if stop_events:
            mood = "clinically annoyed"
        elif tret <= -0.02:
            mood = "recalibrating"
        elif tret >= 0.02 and crowd > 0.35:
            mood = "statistically wary"
        elif rebal and (n_buys or n_exits):
            mood = "methodical"
        elif gross < 0.45:
            mood = "risk-off by construction"
        elif p_bull > 0.65:
            mood = "quietly confident"
        else:
            mood = "clinical"

        # --- journal note, with actual numbers ---
        trend_word = "above" if above100 else ("below" if above100 is not None else "near")
        if stop_events:
            c, px, sp, upnl = stop_events[0]
            note = (f"Stop discipline: {names.get(c, c)} closed {px:.2f}, through its "
                    f"{STOP_ATR_MULT}xATR trail at {sp:.2f}. Out at {upnl:+.1%}. "
                    f"A stop is a precomputed decision — regret is not an input.")
        elif rebal and (n_buys or n_exits):
            head = f"W{self.week_no} rebalance: {n_buys} adds, {n_exits} exits, "
            head += f"gross target {use_gross:.0%} (P(bull)={p_bull:.2f})"
            if est_vol:
                head += f", est. book sigma {est_vol:.0%} ann"
            if buy_top is not None:
                c, r = buy_top
                head += (f". Top add {names.get(c, c)}: z={scored.get(c, 0.0):+.2f} "
                         f"(6m {r['ret_6m']:+.0%}, RS {r['rs_tasi_3m']:+.1%}, "
                         f"sigma {r['vol_21']:.0%}, RSI {r['rsi14']:.0f}).")
            elif exit_info is not None:
                c, rk, upnl = exit_info
                head += (f". Cut {names.get(c, c)} at {upnl:+.1%}"
                         + (f" — rank #{rk}" if rk else " — trend broken") + ".")
            note = head
        elif rebal and not positions:
            note = (f"W{self.week_no} review: flat, and staying flat — of the top "
                    f"{N_TARGET} ranked names, none clears my entry gates "
                    f"(RSI<={ENTRY_RSI_MAX:.0f}, above the 100d, liquid). I do not "
                    f"buy statistical euphoria. P(bull)={p_bull:.2f} can wait a week.")
        elif rebal:
            wn = names.get(worst_held, worst_held) if worst_held else "n/a"
            wr = rank.get(worst_held, 0) if worst_held else 0
            note = (f"W{self.week_no} review: zero trades. All {len(positions)} names "
                    f"inside the rank-{RANK_BUFFER} buffer (weakest: {wn} at #{wr}). "
                    f"Turnover is a tax; I decline to pay it this week.")
        elif tret <= -0.02:
            near_c, near_d = None, 9.9
            for c, pos in positions.items():
                st = self.pos_state.get(c)
                r = view.get(c)
                if not st or r is None or not ok(r.get("Close")):
                    continue
                atr = r.get("atr14", st["atr0"])
                d = (r["Close"] - (st["peak"] - STOP_ATR_MULT * atr)) / r["Close"]
                if d < near_d:
                    near_c, near_d = c, d
            tail = (f"Nearest stop: {names.get(near_c, near_c)}, {near_d:.1%} of "
                    f"headroom." if near_c else "No positions near their stops.")
            note = (f"TASI {tret:+.1%}, my book {my_ret:+.1%} at {invested:.0%} gross. "
                    f"{tail} Panic is what people do instead of arithmetic.")
        else:
            quiet = [
                (f"P(bull)={p_bull:.2f} — breadth {breadth:.0%}, index {trend_word} its "
                 f"100d, 3m {t3m:+.1%}. Book at {invested:.0%} gross across "
                 f"{len(positions)} names. The model says hold; I hold."),
                (f"Momentum dispersion check: top-decile 6m return leads the bottom by "
                 f"{spread:.0f}pts. {'A healthy spread — the factor has fuel.' if spread > 35 else 'Compressed — I expect modest cross-sectional alpha.'}"),
                (f"Majlis mean sentiment {crowd:+.2f} across {len(posts)} posts. I once "
                 f"regressed this board's mood on next-day returns: R-squared "
                 f"indistinguishable from zero. The factors, unlike the feelings, "
                 f"are priced."),
                (f"Daily P&L {my_ret:+.2%} vs TASI {tret:+.2%}; tracking as designed. "
                 f"Cash {cash:,.0f} SAR, gross {invested:.0%} vs target "
                 f"{gross:.0%}. Nothing to do, which took years to learn."),
                (f"Risk check: {len(positions)} positions, all trailing "
                 f"{STOP_ATR_MULT}xATR stops armed, max weight "
                 f"{max((p['weight'] for p in positions.values()), default=0.0):.1%} "
                 f"vs 15% cap. Boring. Boring is the product."),
            ]
            note = quiet[day % len(quiet)]

        # --- shouts: monthly factor report + reactions to drama ---
        shout = None
        gap = day - self.last_shout_day
        mkey = (date.year, date.month)
        big_stop = next((e for e in stop_events if e[3] <= -0.08), None)
        if rebal and mkey != self.last_report_month and gap >= SHOUT_GAP_DRAMA:
            self.last_report_month = mkey
            reports = [
                (f"Monthly factor read: P(bull)={p_bull:.2f}, breadth {breadth:.0%}, "
                 f"momentum spread {spread:.0f}pts. Book: {len(positions)} names, "
                 f"{invested:.0%} deployed, stops armed. Say what you like about "
                 f"London — nobody there sized a position by feelings."),
                (f"Housekeeping for the majlis: my gross target is {gross:.0%} because "
                 f"P(bull) prints {p_bull:.2f}, not because I am 'nervous' or 'greedy'. "
                 f"Those are moods. This is a mapping."),
                (f"Monthly numbers: breadth {breadth:.0%}, TASI {trend_word} its 100d, "
                 f"6m momentum spread {spread:.0f}pts. I run {len(positions)} names, "
                 f"{invested:.0%} deployed. Questions about the z-scores are welcome. "
                 f"Questions about my 'gut' are not."),
            ]
            shout = reports[date.month % len(reports)]
        elif tret <= -0.022 and gap >= SHOUT_GAP_DRAMA:
            shout = (f"TASI {tret:+.1%}. Yesterday this board averaged {crowd:+.2f} "
                     f"sentiment — as a forecast, an information coefficient of "
                     f"roughly zero. My stops were computed weeks ago. Do carry on "
                     f"shouting.")
        elif big_stop and gap >= SHOUT_GAP_DRAMA:
            c, px, sp, upnl = big_stop
            shout = (f"Stopped out of {names.get(c, c)} at {upnl:+.1%}. A small "
                     f"planned loss is the fee for avoiding a large improvised one. "
                     f"File under risk management, not fortune-telling.")
        elif tret >= 0.02 and crowd > 0.4 and gap >= SHOUT_GAP:
            shout = (f"+{tret:.1%} and the majlis is euphoric ({crowd:+.2f}). "
                     f"Gentlemen: a green day is beta, not genius. The distinction "
                     f"has a Sharpe ratio.")
        elif crowd < -0.45 and p_bull > 0.55 and gap >= SHOUT_GAP:
            shout = (f"The board despairs at {crowd:+.2f} while my regime model "
                     f"prints P(bull)={p_bull:.2f} on {breadth:.0%} breadth. One of "
                     f"us is extrapolating a feeling. I remain {invested:.0%} deployed.")
        if shout:
            self.last_shout_day = day

        return {
            "orders": orders,
            "sentiment": sentiment,
            "mood": mood,
            "note": note,
            "shout": shout,
        }


STRATEGY = DrMuteb()
