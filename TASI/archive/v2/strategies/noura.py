"""Noura — the macro strategist. Sector rotation on regime, cash when the tape says so.

Top-down process on the TASI top-50:
  - Regime gate: TASI vs its 100d and 200d SMAs plus breadth (share of the universe
    above its 50d). Score in [-3, +3]; risk-on at >= +2, risk-off at <= -2, and a
    new regime must print 3 straight sessions before she acts on it.
  - Risk-on: overweight the 3 strongest sectors by average 3m return, 2 relative-
    strength leaders per sector, ~92% deployed.
  - Neutral: 2 leading sectors plus the best defensive sleeve, ~65% deployed.
  - Risk-off: rotate into healthcare / telecom / food and hold 60% cash.
    Capital preservation is a position.
  - Petchem cycle rule: she reads the complex (SABIC, Yansab, Sipchem, Kayan...)
    as her oil proxy — Materials is banned from the leadership set while the
    complex's 3m tape is below -10%, and earns an early-cycle bonus when the 1m
    turns up out of a trough.
  - Rotates every 10 sessions, or immediately on a confirmed regime flip. No
    chasing names above RSI 78; illiquid tickers don't make the book.
Crisp macro one-liners. Quietly keeping score against Dr. Muteb.
"""

from __future__ import annotations

import math

from strategy_base import Strategy

# ------------------------------------------------------------------ parameters
REBAL_EVERY = 10            # sessions between scheduled rotations (~2 Tadawul weeks)
FLIP_CONFIRM = 3            # sessions a new regime must persist before she acts
GROSS = {"risk-on": 0.92, "neutral": 0.65, "risk-off": 0.40}
SECTORS_ON = 3              # leadership sectors when risk-on
SECTORS_NEUTRAL = 2         # leaders when neutral (plus one defensive sleeve)
SECTORS_OFF = 2             # defensive sectors when risk-off
PICKS_PER_SECTOR = 2
MAX_W = 0.20                # hard cap per name
BAND = 0.04                 # rebalance dead-band on weights
MIN_ORDER = 3500.0          # SAR, no dust tickets
MIN_LIQ = 1.5e6             # SAR avg daily turnover required of new entries
RSI_CHASE = 78.0            # she does not chase vertical charts
HOLD_RANK_BUFFER = 3        # held name survives while top-3 in its sector
PETCHEM_BAN = -0.10         # Materials banned from leadership below this 3m tape
PETCHEM_TURN = 0.05         # 1m threshold for the early-cycle bonus
BREADTH_HI, BREADTH_LO = 0.58, 0.42
DEFENSIVES = ("Healthcare", "Telecom", "Food & Staples")
PETCHEM = ("2010", "2020", "2060", "2170", "2290", "2310", "2330", "2350", "2380")
SHOUT_GAP = 6               # min sessions between routine shouts
SHOUT_GAP_DRAMA = 3


def ok(x) -> bool:
    return isinstance(x, (int, float)) and x == x and not math.isinf(x)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Noura(Strategy):
    meta = {
        "handle": "noura",
        "name": "Noura",
        "emoji": "📊",
        "tagline": "Sectors are the trade. The regime decides which ones.",
        "risk_style": "macro rotation",
        "color": "#B279A2",
        "character": (
            "A sharp macro strategist who trades the market top-down: a breadth-and-"
            "trend regime gate on the index, sector leadership ranked by 3-month "
            "tape, and a hard rotation into healthcare, telecom and food — 60% cash "
            "— when the gate closes. Reads the oil cycle through the petchem "
            "complex and will not touch Materials while it bleeds. Professional, "
            "concise, and quietly keeping score against Dr. Muteb."
        ),
    }

    def __init__(self):
        self.regime = None          # confirmed regime
        self.pending_raw = None     # candidate regime awaiting confirmation
        self.streak = 0
        self.last_rebal = -999
        self.rot_no = 0             # rotation counter for journal headers
        self.last_shout_day = -99
        self.last_brief_month = None
        self.last_jab_day = -99

    # ------------------------------------------------------------------ decide
    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx["names"]
        sectors = ctx["sectors"]
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        cash = portfolio["cash"]
        equity = max(portfolio["equity"], 1.0)
        positions = portfolio["positions"]
        invested = 1.0 - cash / equity

        # ---- regime gate: index trend + breadth, scored in [-3, +3] ----
        t = view.get("TASI")
        sc = 0
        above100 = above200 = None
        if t is not None:
            tc = t.get("Close", float("nan"))
            s100, s200 = t.get("sma100", float("nan")), t.get("sma200", float("nan"))
            if ok(tc) and ok(s100):
                above100 = tc > s100
                sc += 1 if above100 else -1
            if ok(tc) and ok(s200):
                above200 = tc > s200
                sc += 1 if above200 else -1
        if breadth >= BREADTH_HI:
            sc += 1
        elif breadth <= BREADTH_LO:
            sc -= 1
        raw = "risk-on" if sc >= 2 else ("risk-off" if sc <= -2 else "neutral")

        flipped = None
        if self.regime is None:
            self.regime = raw
        elif raw != self.regime:
            if raw == self.pending_raw:
                self.streak += 1
            else:
                self.pending_raw, self.streak = raw, 1
            if self.streak >= FLIP_CONFIRM:
                flipped = (self.regime, raw)
                self.regime = raw
                self.pending_raw, self.streak = None, 0
        else:
            self.pending_raw, self.streak = None, 0
        regime = self.regime

        # ---- sector map: avg 3m return per sector + per-stock RS scores ----
        sec_rows = {}           # sector -> list[(code, row)]
        for c, r in view.items():
            if c == "TASI":
                continue
            px = r.get("Close", float("nan"))
            if not (ok(px) and px > 0) or not ok(r.get("ret_3m", float("nan"))):
                continue
            sec_rows.setdefault(sectors.get(c, "?"), []).append((c, r))
        sec_score = {s: sum(r["ret_3m"] for _, r in rows) / len(rows)
                     for s, rows in sec_rows.items() if len(rows) >= 2}

        # petchem complex read — her oil proxy
        p3, p1, np_ = 0.0, 0.0, 0
        for c in PETCHEM:
            r = view.get(c)
            if r is not None and ok(r.get("ret_3m", float("nan"))):
                p3 += r["ret_3m"]
                p1 += r["ret_1m"] if ok(r.get("ret_1m", float("nan"))) else 0.0
                np_ += 1
        pet3 = p3 / np_ if np_ else 0.0
        pet1 = p1 / np_ if np_ else 0.0
        pet_banned = pet3 < PETCHEM_BAN
        pet_turn = (pet1 > PETCHEM_TURN) and (pet3 <= 0.02)
        if "Materials" in sec_score and pet_turn:
            sec_score["Materials"] += 0.05      # early-cycle turn bonus

        ranked_secs = sorted(sec_score, key=lambda s: (-sec_score[s], s))
        lead = [s for s in ranked_secs if not (s == "Materials" and pet_banned)]
        def_ranked = [s for s in ranked_secs if s in DEFENSIVES]

        # ---- choose the sector book for the current regime ----
        if regime == "risk-on":
            book_secs = lead[:SECTORS_ON]
        elif regime == "neutral":
            book_secs = lead[:SECTORS_NEUTRAL]
            for s in def_ranked:
                if s not in book_secs:
                    book_secs = book_secs + [s]
                    break
        else:
            book_secs = def_ranked[:SECTORS_OFF]
        gross = GROSS[regime]

        # ---- within each sector: relative-strength leaders, sticky holds ----
        chosen = []
        for s in book_secs:
            rows = sec_rows.get(s, [])
            scored = []
            for c, r in rows:
                rs = r.get("rs_tasi_3m", float("nan"))
                m1 = r.get("ret_1m", float("nan"))
                scored.append((c, (rs if ok(rs) else 0.0) + 0.5 * (m1 if ok(m1) else 0.0), r))
            scored.sort(key=lambda x: (-x[1], x[0]))
            rank_in = {c: i + 1 for i, (c, _, _) in enumerate(scored)}
            picks = [c for c, _, _ in scored
                     if c in positions and rank_in[c] <= HOLD_RANK_BUFFER][:PICKS_PER_SECTOR]
            for c, _, r in scored:
                if len(picks) >= PICKS_PER_SECTOR:
                    break
                if c in picks:
                    continue
                rsi = r.get("rsi14", float("nan"))
                if ok(rsi) and rsi > RSI_CHASE:
                    continue
                liq = r.get("vol_sma20", float("nan"))
                liq_sar = liq * r["Close"] if ok(liq) else r.get("turnover_sar", 0.0)
                if not ok(liq_sar) or liq_sar < MIN_LIQ:
                    continue
                picks.append(c)
            chosen.extend((c, s) for c in picks)

        # ---- rotation day? scheduled cadence, or a confirmed flip ----
        orders = []
        rebal = bool(chosen) and (flipped is not None or day - self.last_rebal >= REBAL_EVERY)
        n_buys = n_sells = 0
        sold_note = None
        if rebal:
            self.last_rebal = day
            self.rot_no += 1
            target_names = {c for c, _ in chosen}
            w_each = min(MAX_W, gross / max(len(chosen), 1))
            proceeds = 0.0
            for c, pos in positions.items():
                if c in target_names or view.get(c) is None:
                    continue
                why = (f"rotation out: {sectors.get(c, '?')} not in the "
                       f"{regime} book")
                if sectors.get(c) == "Materials" and pet_banned:
                    why = f"petchem complex {pet3:+.1%} 3m — Materials is off limits"
                orders.append({"code": c, "side": "sell", "all": True, "reason": why})
                proceeds += pos["value"]
                n_sells += 1
                if sold_note is None:
                    sold_note = (c, pos["unrealized_pct"])
            budget = cash + proceeds * 0.995 - 0.005 * equity
            # trims first
            for c, _s in chosen:
                cur_w = positions.get(c, {}).get("weight", 0.0)
                if cur_w > w_each + BAND and c in positions:
                    frac = (cur_w - w_each) / cur_w
                    orders.append({"code": c, "side": "sell",
                                   "fraction": round(frac, 4),
                                   "reason": f"trim {cur_w:.1%} -> {w_each:.1%}"})
                    budget += frac * positions[c]["value"] * 0.995
            # buys, strongest sector first (chosen is already in sector order)
            for c, s in chosen:
                cur_w = positions.get(c, {}).get("weight", 0.0)
                gap = (w_each - cur_w) * equity
                if w_each - cur_w <= BAND or gap < MIN_ORDER:
                    continue
                amt = min(gap, budget)
                if amt < MIN_ORDER:
                    continue
                orders.append({"code": c, "side": "buy", "sar": round(amt, 2),
                               "reason": (f"{s} leadership, sector 3m "
                                          f"{sec_score.get(s, 0.0):+.1%}, "
                                          f"target {w_each:.0%}")})
                budget -= amt * 1.003
                n_buys += 1
        else:
            # drift control between rotations — the cap is the cap
            for c, pos in positions.items():
                if pos["weight"] > MAX_W + 0.03 and view.get(c) is not None:
                    frac = (pos["weight"] - MAX_W) / pos["weight"]
                    orders.append({"code": c, "side": "sell",
                                   "fraction": round(frac, 4),
                                   "reason": f"drift {pos['weight']:.1%} > {MAX_W:.0%} cap"})

        # ---- majlis read: the crowd, and one particular quant ----
        posts = ctx.get("majlis", []) or []
        others = [p for p in posts if p.get("handle") != "noura"]
        crowd = (sum(float(p.get("sentiment", 0.0)) for p in others) / len(others)
                 if others else 0.0)
        muteb = next((p for p in others if p.get("handle") == "dr_muteb"), None)

        # ---- sentiment: the regime score, perturbed by today's tape ----
        sentiment = clamp(0.26 * sc + 1.6 * clamp(tret, -0.04, 0.04)
                          + 0.5 * (breadth - 0.5), -0.9, 0.9)

        # ---- mood ----
        if flipped:
            mood = "regime shift"
        elif rebal and (n_buys or n_sells):
            mood = "rotating"
        elif regime == "risk-off":
            mood = "thawing" if sc >= 2 else "defensive"
        elif tret <= -0.02:
            mood = "watchful"
        elif regime == "risk-on":
            mood = "tightening up" if sc <= -2 else "constructive"
        else:
            mood = "measured"

        # ---- journal: crisp macro one-liners with real numbers ----
        top_s = ranked_secs[0] if ranked_secs else "n/a"
        low_s = ranked_secs[-1] if ranked_secs else "n/a"
        t100 = "above" if above100 else ("below" if above100 is not None else "near")
        t200 = "above" if above200 else ("below" if above200 is not None else "near")
        pet_word = ("contracting" if pet3 < -0.05 else
                    "turning" if pet_turn else
                    "expanding" if pet3 > 0.05 else "flat")
        if flipped:
            note = (f"Regime flip confirmed: {flipped[0]} -> {flipped[1]}. Index "
                    f"{t100} the 100d, {t200} the 200d, breadth {breadth:.0%}. "
                    f"Gross goes to {gross:.0%}; the book follows the gate, not my "
                    f"feelings about it.")
        elif rebal and (n_buys or n_sells):
            secs_txt = ", ".join(f"{s} {sec_score.get(s, 0.0):+.1%}" for s in book_secs)
            note = (f"Rotation #{self.rot_no} ({regime}): {n_buys} adds, {n_sells} "
                    f"exits. Book: {secs_txt}. Gross {gross:.0%}, cash "
                    f"{1 - gross:.0%}." +
                    (f" Materials stays benched — complex {pet3:+.1%} 3m."
                     if pet_banned and regime != "risk-off" else ""))
        elif rebal:
            note = (f"Rotation #{self.rot_no}: reviewed, unchanged. Leadership still "
                    f"{top_s} ({sec_score.get(top_s, 0.0):+.1%} 3m), regime {regime}, "
                    f"{invested:.0%} deployed. Turnover without information is just "
                    f"a donation to the exchange.")
        elif tret <= -0.02:
            note = (f"TASI {tret:+.1%} on {breadth:.0%} breadth. Regime score "
                    f"{sc:+d} ({regime}); the gate was built for days like this. "
                    f"Cash {cash / equity:.0%}, and I sleep fine.")
        else:
            quiet = [
                (f"Macro read: index {t100} 100d / {t200} 200d, breadth "
                 f"{breadth:.0%}, score {sc:+d} -> {regime}. Positioned "
                 f"{invested:.0%} accordingly."),
                (f"Petchem complex: 3m {pet3:+.1%}, 1m {pet1:+.1%} — the cycle is "
                 f"{pet_word}. That is my oil dashboard; everything else is "
                 f"headlines."),
                (f"Leadership check: {top_s} {sec_score.get(top_s, 0.0):+.1%} over "
                 f"3m vs {low_s} {sec_score.get(low_s, 0.0):+.1%} at the back. "
                 f"Rotation is the only free lunch on this tape."),
                (f"Book: {len(positions)} names across "
                 f"{len({sectors.get(c) for c in positions}) if positions else 0} "
                 f"sectors, {invested:.0%} gross vs {gross:.0%} target. Next "
                 f"scheduled rotation in {max(0, REBAL_EVERY - (day - self.last_rebal))} "
                 f"sessions."),
                (f"Majlis mean {crowd:+.2f}; my regime score {sc:+d}. Sentiment is a "
                 f"coincident indicator at best — breadth {breadth:.0%} is the one "
                 f"that pays."),
            ]
            note = quiet[day % len(quiet)]

        # ---- shouts: flips always, monthly brief, drama, the occasional jab ----
        shout = None
        gap_days = day - self.last_shout_day
        mkey = (date.year, date.month)
        if flipped:
            arrow = {"risk-on": "opening", "risk-off": "closing",
                     "neutral": "half-open"}[flipped[1]]
            shout = (f"Regime call: {flipped[0]} -> {flipped[1]}. Breadth "
                     f"{breadth:.0%}, index {t100} its 100d. The gate is {arrow} — "
                     f"gross to {gross:.0%}. You heard it here first.")
        elif rebal and mkey != self.last_brief_month and gap_days >= SHOUT_GAP_DRAMA:
            self.last_brief_month = mkey
            briefs = [
                (f"Monthly macro brief: regime {regime} (score {sc:+d}), breadth "
                 f"{breadth:.0%}. Leadership: {top_s} {sec_score.get(top_s, 0.0):+.1%} "
                 f"3m. Petchem complex {pet3:+.1%} — {pet_word}. Positioned "
                 f"{gross:.0%} gross."),
                (f"Brief for the majlis: {regime} tape, {top_s} leads at "
                 f"{sec_score.get(top_s, 0.0):+.1%} 3m, {low_s} lags at "
                 f"{sec_score.get(low_s, 0.0):+.1%}. I own sectors, not stories. "
                 f"Cash {1 - gross:.0%}."),
                (f"Sector scoreboard: {top_s} first, {low_s} last, spread "
                 f"{(sec_score.get(top_s, 0.0) - sec_score.get(low_s, 0.0)):.0%}. "
                 f"Regime {regime}; the complex reads {pet3:+.1%}. Rotation is "
                 f"positioning, the rest is noise."),
            ]
            shout = briefs[date.month % len(briefs)]
        elif abs(tret) >= 0.022 and gap_days >= SHOUT_GAP_DRAMA:
            if tret < 0:
                shout = (f"TASI {tret:+.1%}. Breadth {breadth:.0%}, regime score "
                         f"{sc:+d}. I'm {invested:.0%} invested by design, not by "
                         f"hope — the gate did its job before the tape did this.")
            else:
                shout = (f"TASI {tret:+.1%} — beta is generous today. The question "
                         f"is leadership: {top_s} {sec_score.get(top_s, 0.0):+.1%} "
                         f"over 3m. Own the sector, not the euphoria.")
        elif (muteb is not None and gap_days >= SHOUT_GAP
              and day - self.last_jab_day >= 20
              and abs(float(muteb.get("sentiment", 0.0)) - sentiment) > 0.55):
            self.last_jab_day = day
            m_sent = float(muteb.get("sentiment", 0.0))
            shout = (f"Dr. Muteb prints {m_sent:+.2f} while the regime score reads "
                     f"{sc:+d} on {breadth:.0%} breadth. Factors are lovely; "
                     f"regimes decide whether they get paid. We'll compare "
                     f"equity curves.")
        if shout:
            self.last_shout_day = day

        return {
            "orders": orders,
            "sentiment": sentiment,
            "mood": mood,
            "note": note,
            "shout": shout,
        }


STRATEGY = Noura()
