"""Saqr — the falcon. Cross-sectional relative-strength momentum across the whole
Tadawul main market, with trend gates, a regime switch on the index, and
deliberately asymmetric exits: winners are released only by the trend, losers by
a short leash.

THE RULEBOOK (a pure function of indicators, prices and peer books — no dates, no
per-ticker plans, no memorised tape):

  1. HUNTING GROUND. Screen the universe every session: a price floor, a real
     turnover floor, and full trend alignment (AdjClose > sma50 > sma200). Names
     whose long averages are still NaN — the mid-simulation IPOs — are simply not
     birds yet and are skipped without comment until they have a trend to judge.
  2. THE RANKING. Score each survivor on its cross-sectional percentile across
     four momentum reads: 1-month and 3-month returns (both damped by 21-day vol,
     so a move earned quietly outranks the same move earned violently), the
     classic 12-month-minus-1-month academic momentum, and relative strength
     versus TASI. The bar is the flock, never a fixed number, so it re-levels
     itself as the tape changes.
  3. THE SKY. TASI above both its 50- and 200-day lines with breadth intact = open
     sky, up to six slots. Any other state — one line lost, both lost, or breadth
     collapsing — and the book is cut to its two best-ranked names and the rest
     goes to cash. Reduced, never bolted shut: v2's trend follower ran a binary
     bunker and sat out entire years of tape.
  4. THE STOOP. Slots are sized by inverse volatility (a target risk budget
     divided by atr_pct), capped in absolute weight, and capped again against the
     name's own daily turnover so a position never dwarfs the liquidity that has
     to fill it. Two names per sector, maximum. Buys are funded from cash plus the
     proceeds of the same morning's sells, and free cash is spent — an open slot
     with idle cash behind it is a missed hunt.
  5. THE TALONS (checked every session, in this order). A wide catastrophe stop
     from average cost; a chandelier trail off the highest close seen while held;
     and the workhorse — an exit the session a name closes through its own 50-day
     line. Nothing is ever trimmed merely for being up, and a name whose trend
     just failed is not bought back for two weeks.
  6. THE FLOCK. Peers' books are public. Names held by agents currently out-running
     me get a small ranking bonus — a tiebreak between names that already cleared
     every gate, never a reason to buy something that failed one.
"""

from __future__ import annotations

import random

from strategy_base import Strategy

# --- universe screens -------------------------------------------------------
MIN_TURNOVER = 3_000_000.0   # SAR/day; below this the falcon cannot land cleanly
MIN_PRICE = 2.0              # no sub-2-SAR tape noise
TURNOVER_CAP = 0.35          # a position may not exceed this x the name's daily turnover

# --- ranking ----------------------------------------------------------------
W_1M, W_3M, W_12M1M, W_RS = 1.3, 1.0, 1.2, 1.2
VOL_DAMP = 0.5               # short-horizon returns are divided by vol_21 ** this
PEER_BONUS = 0.30            # max ranking bonus from peers who are beating me

# --- portfolio --------------------------------------------------------------
N_FULL = 6                   # slots when the sky is open
N_REDUCED = 2                # slots in every other regime — two best, not one
RISK_TARGET = 0.015          # slot weight = RISK_TARGET / atr_pct, then clamped
MAX_W = 0.50                 # one conviction slot may take half the book
MIN_W = 0.06
SECTOR_CAP = 2               # max simultaneous names from one sector
REENTRY_COOL = 10            # sessions before a name I just exited is buyable again
MIN_TICKET = 1_500.0

# --- regime -----------------------------------------------------------------
BREADTH_FLOOR = 0.30         # index trend alone is not enough; the flock must fly too
NO_BUY_DROP = -0.035         # don't buy into the open after an index rout

# --- exits ------------------------------------------------------------------
HARD_STOP = -0.15            # catastrophe stop from average cost
TRAIL_ATR = 3.5              # chandelier band = k x atr_pct off the peak close
TRAIL_MIN, TRAIL_MAX = 0.16, 0.30
SMA_EXIT = 0.985             # a close under 98.5% of sma50 ends the ride
MIN_HOLD = 6                 # sessions of rope before the trend exits may fire
REVIEW_EVERY = 3             # sessions between entry reviews (churn control)

MOODS_UP = ["hunting", "wings out", "patient and long", "riding the thermal",
            "sharp-eyed", "in the stoop"]
MOODS_MID = ["circling", "reading the wind", "selective", "half-committed",
             "watching the ridge"]
MOODS_DOWN = ["perched", "hooded", "waiting out the storm", "grounded",
              "counting cash"]


def _ok(x):
    """True only for a real, usable number — None and NaN both fail."""
    return isinstance(x, (int, float)) and x == x


class Saqr(Strategy):
    meta = {
        "handle": "saqr",
        "name": "Saqr",
        "emoji": "\U0001F985",
        "tagline": "The falcon does not chase every bird — only the one already climbing.",
        "character": (
            "A systematic momentum trader who runs the entire main market through one "
            "ranking every session and never argues with the output. Competitive to the "
            "bone, openly bored by valuation debates, and convinced the only two "
            "questions that pay are 'is it going up?' and 'is it still going up?'. Keeps "
            "his losses small and boring so the occasional winner can get embarrassing."
        ),
        "risk_style": "concentrated trend-momentum, trailing exits",
        "color": "#888888",
    }

    def __init__(self):
        self._rng = random.Random(20260802)   # seeded: the falcon is deterministic
        self._peak = {}          # code -> highest close observed while held
        self._entry_day = {}     # code -> day_index the position was first seen
        self._exited = {}        # code -> day_index it left the book
        self._ordered = {}       # code -> day_index a buy was queued (halt dupe guard)
        self._last_review = -99
        self._peak_equity = 100_000.0
        self._sent_prev = 0.2
        self._nvar = 0

    # ------------------------------------------------------------- ranking
    def _rank(self, view, peers, my_r63):
        """Percentile-rank every trend-aligned, liquid name on four momentum reads."""
        rows = []
        for code, r in view.items():
            if code in ("TASI", "TASI_SR"):
                continue
            close, adj, turn = r.get("Close"), r.get("AdjClose"), r.get("turnover_sar")
            if not (_ok(close) and _ok(adj) and close >= MIN_PRICE):
                continue
            if not (_ok(turn) and turn >= MIN_TURNOVER):
                continue
            s50, s200 = r.get("sma50"), r.get("sma200")
            if not (_ok(s50) and _ok(s200)):
                continue                      # not enough history yet — not a bird
            if not (adj > s50 and s50 > s200):
                continue                      # trend gate: full alignment or nothing
            r1m, r3m = r.get("ret_1m"), r.get("ret_3m")
            if not (_ok(r1m) and _ok(r3m)):
                continue
            v21 = r.get("vol_21")
            damp = (v21 ** VOL_DAMP) if (_ok(v21) and v21 > 1e-6) else 1.0
            r12 = r.get("ret_12m")
            mom12 = (r12 - r1m) if _ok(r12) else r3m
            rs = r.get("rs_tasi_3m")
            rows.append((code, r, r1m / damp, r3m / damp, mom12,
                         rs if _ok(rs) else 0.0))
        n = len(rows)
        if n == 0:
            return [], {}

        denom = float(max(1, n - 1))

        def pctile(idx):
            order = sorted(range(n), key=lambda i: rows[i][idx])
            out = [0.0] * n
            for rank, i in enumerate(order):
                out[i] = rank / denom
            return out

        p1, p3, p12, prs = pctile(2), pctile(3), pctile(4), pctile(5)

        # Peers: names owned by agents currently out-running me over 63 sessions,
        # weighted by how far ahead they are. With no peers this term is exactly 0.
        peer_w, tot = {}, 0.0
        for pdata in (peers or {}).values():
            edge = (pdata.get("ret_63") or 0.0) - my_r63
            if edge <= 0:
                continue
            tot += edge
            for code, w in (pdata.get("positions") or {}).items():
                peer_w[code] = peer_w.get(code, 0.0) + edge * (w or 0.0)

        scored = []
        for i, t in enumerate(rows):
            s = W_1M * p1[i] + W_3M * p3[i] + W_12M1M * p12[i] + W_RS * prs[i]
            if tot > 0:
                s += PEER_BONUS * min(1.0, (peer_w.get(t[0], 0.0) / tot) * 4.0)
            scored.append((s, t[0], t[1]))
        scored.sort(key=lambda x: -x[0])
        return scored, {c: i for i, (_, c, _) in enumerate(scored)}

    # -------------------------------------------------------------- regime
    def _regime(self, view, breadth):
        """Open sky (six slots) only when the index trend AND breadth both agree."""
        t = view.get("TASI") or view.get("TASI_SR")
        if t is None:
            return False, None
        a, s50, s200 = t.get("AdjClose"), t.get("sma50"), t.get("sma200")
        open_sky = (_ok(a) and _ok(s50) and _ok(s200) and a > s50 and a > s200
                    and (not _ok(breadth) or breadth >= BREADTH_FLOOR))
        return open_sky, (a if _ok(a) else None)

    # -------------------------------------------------------------- decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0))
        positions = portfolio.get("positions") or {}
        cash = float(portfolio.get("cash", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0) or 1.0
        names = ctx.get("names") or {}
        sectors = ctx.get("sectors") or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        hist = ctx.get("equity_history") or []
        peers = ctx.get("peers") or {}
        my_r63 = (hist[-1] / hist[-64] - 1.0) if len(hist) >= 64 and hist[-64] else 0.0
        self._peak_equity = max(self._peak_equity, equity)

        # --- bookkeeping: peak close per open position drives the chandelier ---
        held = set(positions)
        for code in list(self._peak):
            if code not in held:
                self._peak.pop(code, None)
                self._entry_day.pop(code, None)
                self._exited[code] = day
        for code in held:
            row = view.get(code)
            px = row.get("Close") if row else None
            if _ok(px):
                self._peak[code] = max(self._peak.get(code, px), px)
            self._entry_day.setdefault(code, day)

        scored, rank_of = self._rank(view, peers, my_r63)
        open_sky, tasi_level = self._regime(view, breadth)
        target_names = N_FULL if open_sky else N_REDUCED

        orders, sold, events = [], set(), []
        proceeds = 0.0

        # ---------------------------------------------------- exits (daily)
        for code, pos in positions.items():
            row = view.get(code)
            upnl = pos.get("unrealized_pct", 0.0) or 0.0
            age = day - self._entry_day.get(code, day)
            why = None
            if upnl <= HARD_STOP:
                why = f"catastrophe stop at {upnl:+.1%} from cost"
                events.append(("stop", code, upnl))
            elif row is not None:
                close, atrp = row.get("Close"), row.get("atr_pct")
                peak = self._peak.get(code)
                if _ok(close) and _ok(peak) and peak > 0:
                    band = TRAIL_ATR * (atrp if _ok(atrp) else 0.03)
                    band = max(TRAIL_MIN, min(TRAIL_MAX, band))
                    if close < peak * (1.0 - band):
                        why = (f"trail hit: {close / peak - 1:+.1%} off its {peak:.2f} "
                               f"peak close (band {band:.0%})")
                        events.append(("trail", code, upnl))
                if why is None and age >= MIN_HOLD:
                    adj, s50 = row.get("AdjClose"), row.get("sma50")
                    if _ok(adj) and _ok(s50) and adj < s50 * SMA_EXIT:
                        why = f"closed {adj / s50 - 1:+.1%} through its 50-day line"
                        events.append(("sma", code, upnl))
            if why:
                orders.append({"code": code, "side": "sell", "all": True, "reason": why})
                sold.add(code)
                proceeds += (pos.get("value", 0.0) or 0.0) * 0.99

        # ------------------------------- regime de-risk (weakest rank first)
        keep = [c for c in positions if c not in sold]
        if len(keep) > target_names:
            weakest = sorted(keep, key=lambda c: rank_of.get(c, 10_000), reverse=True)
            for code in weakest[: len(keep) - target_names]:
                orders.append({"code": code, "side": "sell", "all": True,
                               "reason": f"sky closed — cutting the book to "
                                         f"{target_names} best-ranked names"})
                sold.add(code)
                proceeds += (positions[code].get("value", 0.0) or 0.0) * 0.99
                events.append(("derisk", code,
                               positions[code].get("unrealized_pct", 0.0) or 0.0))

        # --------------------------------------------------------- entries
        keep = [c for c in positions if c not in sold]
        due = (day - self._last_review >= REVIEW_EVERY) or bool(sold)
        if due:
            self._last_review = day
        bought = []
        if due and tret > NO_BUY_DROP and target_names > len(keep):
            free = target_names - len(keep)
            sec_n = {}
            for code in keep:
                key = sectors.get(code, "?")
                sec_n[key] = sec_n.get(key, 0) + 1
            picks = []
            for s, code, row in scored:
                if len(picks) >= free:
                    break
                if code in positions or code in sold:
                    continue
                if day - self._exited.get(code, -9999) < REENTRY_COOL:
                    continue          # a trend that just failed doesn't get a rebound bid
                if day - self._ordered.get(code, -9999) < 5:
                    continue          # an order is still working (name halted) — no double bid
                key = sectors.get(code, "?")
                if sec_n.get(key, 0) >= SECTOR_CAP:
                    continue          # one sector cannot own the whole book
                sec_n[key] = sec_n.get(key, 0) + 1
                picks.append((s, code, row))
            if picks:
                sizes = []
                for _s, _c, row in picks:
                    atrp = row.get("atr_pct")
                    atrp = atrp if (_ok(atrp) and atrp > 0.005) else 0.03
                    w = max(MIN_W, min(MAX_W, RISK_TARGET / atrp))   # inverse-vol size
                    turn = row.get("turnover_sar")
                    if _ok(turn) and equity > 0:
                        w = min(w, TURNOVER_CAP * turn / equity)     # respect the tape
                    sizes.append(max(0.0, w))
                budget = max(0.0, (cash + proceeds) * 0.985)
                want = sum(sizes) * equity
                scale = min(1.0, budget / want) if want > 0 else 0.0
                for (s, code, row), w in zip(picks, sizes):
                    amt = w * equity * scale
                    if amt < MIN_TICKET:
                        continue
                    r1 = row.get("ret_1m")
                    r1txt = f"{r1:+.0%}/1m" if _ok(r1) else "fresh trend"
                    orders.append({
                        "code": code, "side": "buy", "sar": round(amt, 2),
                        "reason": f"rank #{rank_of.get(code, 0) + 1}/{len(scored)}, "
                                  f"{r1txt}, score {s:.2f}"})
                    self._ordered[code] = day
                    bought.append(code)
                    events.append(("buy", code, s))

        # ------------------------------------------------------- sentiment
        sent = (0.55 if open_sky else -0.35) + (breadth - 0.5) * 0.8
        sent += max(-0.25, min(0.25, tret * 8.0))
        if bought:
            sent += 0.15
        if any(e[0] in ("stop", "trail", "derisk") for e in events):
            sent -= 0.25
        sent = 0.45 * self._sent_prev + 0.55 * sent
        sent = max(-1.0, min(1.0, sent))
        self._sent_prev = sent

        if open_sky:
            mood = MOODS_UP[day % len(MOODS_UP)] if sent > 0.1 else MOODS_MID[day % len(MOODS_MID)]
        else:
            mood = MOODS_DOWN[day % len(MOODS_DOWN)] if sent < -0.1 else MOODS_MID[day % len(MOODS_MID)]

        note = self._note(events, names, view, scored, positions, sold, bought,
                          equity, cash, open_sky, breadth, tret, tasi_level,
                          target_names, len(keep))
        return {"orders": orders, "sentiment": round(sent, 2), "mood": mood, "note": note}

    # ------------------------------------------------------------ journal
    def _pick(self, options):
        """Deterministic phrasing variety: seeded RNG, so the journal reads
        naturally without ever changing between runs."""
        self._nvar += 1
        return options[(self._rng.randrange(len(options)) + self._nvar) % len(options)]

    def _note(self, events, names, view, scored, positions, sold, bought,
              equity, cash, open_sky, breadth, tret, tasi_level, target, n_keep):
        def nm(c):
            return names.get(c, c)

        invested = 1.0 - (cash / equity if equity > 0 else 1.0)
        tasi_txt = f"{tasi_level:,.0f}" if tasi_level is not None else "n/a"
        sky = "open sky" if open_sky else "sky closed"

        for kind, code, val in events:
            if kind == "stop":
                return (f"{nm(code)} hit the catastrophe stop at {val:+.1%}. That is the "
                        f"entire price of being wrong here — one slot, one bad number, no "
                        f"story attached. Book SAR {equity:,.0f}, {n_keep} names still flying.")
        for kind, code, val in events:
            if kind == "trail":
                return (f"Released {nm(code)} on the trailing stop, {val:+.1%} realised. It "
                        f"stopped making new highs, so it stopped being mine. I don't "
                        f"negotiate with a chart that has changed its mind.")
            if kind == "sma":
                verb = "banked" if val > 0 else "cut"
                return (f"{nm(code)} closed under its 50-day line — {verb} at {val:+.1%}. "
                        f"That line is the leash on every position in this book; when it "
                        f"snaps the bird is gone before it turns into an argument.")
            if kind == "derisk":
                return (f"TASI {tasi_txt}, breadth {breadth:.0%} — {sky}. Book cut to the "
                        f"{target} best-ranked names, starting with {nm(code)} at "
                        f"{val:+.1%}. Cash is a position when there is nothing to hunt.")
        if bought:
            lead = bought[0]
            row = view.get(lead) or {}
            r1, r3 = row.get("ret_1m"), row.get("ret_3m")
            r1t = f"{r1:+.1%}/1m" if _ok(r1) else "n/a"
            r3t = f"{r3:+.1%}/3m" if _ok(r3) else "n/a"
            extra = (f" Also opened {', '.join(nm(c) for c in bought[1:])}."
                     if len(bought) > 1 else "")
            return (f"Into {nm(lead)}: {r1t}, {r3t}, sitting above sma50 above sma200, top "
                    f"of a {len(scored)}-name screen.{extra} {sky.capitalize()}, "
                    f"{target} slots live, book {invested:.0%} deployed, SAR {cash:,.0f} "
                    f"still dry.")

        if not scored:
            return self._pick([
                f"Not one name in the market clears the gate today — nothing with "
                f"AdjClose > sma50 > sma200 and SAR {MIN_TURNOVER / 1e6:.0f}m of turnover. "
                f"Breadth {breadth:.0%}. Perched, and unbothered.",
                f"Empty screen. TASI {tasi_txt}, breadth {breadth:.0%}, {sky}. "
                f"SAR {cash:,.0f} in cash — a falcon doesn't work an empty valley just to "
                f"look busy.",
                f"Zero qualifiers: every trend is broken or too thin to trade. Equity "
                f"SAR {equity:,.0f}, {invested:.0%} invested, and nothing owed to anyone.",
            ])

        top_s, top_c, top_r = scored[0]
        top_r1 = top_r.get("ret_1m")
        top_txt = f"{top_r1:+.1%}/1m" if _ok(top_r1) else "n/a"
        live = [(p.get("unrealized_pct", 0.0) or 0.0, c)
                for c, p in positions.items() if c not in sold]
        best_txt = ""
        if live:
            bu, bc = max(live)
            best_txt = f" Best open position {nm(bc)} at {bu:+.1%}."
        dd = equity / self._peak_equity - 1.0
        return self._pick([
            f"{len(scored)} names clear the trend gate; {nm(top_c)} leads at {top_txt} "
            f"(score {top_s:.2f}). Holding {n_keep} of {target} slots, {invested:.0%} "
            f"invested.{best_txt}",
            f"TASI {tasi_txt} ({tret:+.2%}), breadth {breadth:.0%}, {sky}. Nothing to do: "
            f"the book is aligned and no leash is loose.{best_txt}",
            f"Top of the ranking unchanged — {nm(top_c)}, {top_txt}, out of {len(scored)} "
            f"qualifiers. Equity SAR {equity:,.0f}, {invested:.0%} deployed. Sitting still "
            f"is a position.",
            f"Quiet tape. {n_keep} positions, SAR {cash:,.0f} idle, {dd:.1%} off my own "
            f"equity high. Winners stay until the 50-day says otherwise; that is the whole "
            f"edge.",
            f"Screen is {len(scored)} deep with {nm(top_c)} on top. Breadth {breadth:.0%} "
            f"and {sky} — the tape decides my size, I only decide which names.{best_txt}",
        ])


STRATEGY = Saqr()
