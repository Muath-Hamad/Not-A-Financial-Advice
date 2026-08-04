"""Zahab — the golden standard. He does not read charts; he reads the majlis.

Zahab arrived last and admitted the obvious: eight people have been trading
this market in public for months, and their books are the only research he
needs. So he built a fund of funds inside the majlis.

  - Every close he writes down each agent's equity, so he owns something none
    of them own: their track records, measured the same way, side by side.
  - He grades them on blended trailing return (63d and 21d) minus two charges:
    one for the volatility of their equity curve, and one for how fast they
    turn their book over. Being right calmly beats being right loudly, and a
    trader he cannot keep up with is a trader he cannot copy — at one day's lag
    he would only ever buy their exits.
  - The five best get softmax weights — the leader carries the most, nobody
    carries everything — and their books are blended into a single conviction
    map of *what share of their risk* sits in each name. That map is smoothed
    day over day, so a colleague's flicker never becomes Zahab's commission.
    12% cap per name, a liquidity screen measured against the day's own tape,
    and a weekly rebalance behind a 3% drift band. He tried a tighter band and
    a shorter panel; both just bought him more commission.
  - He also keeps the tuition ledger: every riyal of realized profit and loss any
    agent has ever booked in a name, against every riyal they pushed through it,
    both decayed slowly. Judged per riyal deployed, not per riyal lost — the
    majlis trades Aramco every week, so raw losses there mean nothing. Past five
    halalas of loss on the riyal, Zahab stops enrolling: somebody already paid
    for that lesson and he intends to learn it for free.
  - Exposure mirrors the leaders: when they raise cash he raises cash, when
    their blended 21-day return turns negative he cuts, and when nobody in the
    majlis is making money he stops pretending someone is. Where their names
    fail his screens he stands in the Kingdom's anchors rather than guessing.
  - First 63 sessions he owns eight mega-caps equal-weighted and says nothing
    useful, because a track record shorter than a quarter is a rumour.

He credits everyone by name. Especially the ones he is quietly fading.
"""

from __future__ import annotations

import math

from strategy_base import Strategy


def ok(x) -> bool:
    """True if x is a real, usable number (guards NaN/None)."""
    return isinstance(x, (int, float)) and x == x


# The majlis, by their proper names. Zahab never refers to a colleague by handle.
PEER_NAMES = {
    "um_khalid": "Um Khalid",
    "abu_shanab": "Abu Shanab",
    "shadi": "Shadi",
    "dr_muteb": "Dr. Muteb",
    "noura": "Noura",
    "abu_fahad": "Abu Fahad",
    "saleh": "Saleh",
    "lulu": "Lulu",
}

# Cold-start basket: the eight names nobody in the Kingdom has to justify.
ANCHORS = ["2222", "1120", "1180", "7010", "2010", "1150", "8210", "2280"]

COLD_DAYS = 63          # sessions of pure observation before he copies anyone
ANCHOR_W = 0.115        # equal weight during the cold start (8 x 11.5% = 92%)

TOP_K = 5               # size of the panel he backs (softmax-weighted by grade)
TAU = 0.18              # softmax temperature over peer scores
BLEND_EQ = 0.12         # small equal-weight floor so no one is copied blindly
TAU_SENT = 0.12         # softmax temperature for listening to the majlis
W_63, W_21 = 0.72, 0.28  # blended trailing performance: the quarter outranks the month
LAMBDA_VOL = 0.08       # light charge for a jagged equity curve
LAMBDA_CHURN = 0.30     # charge for book turnover — I can only copy what I can follow
CHURN_A = 0.03          # EMA on peer daily turnover (~33 sessions)
SCORE_A = 0.12          # EMA on peer scores: the leaderboard should not flicker

SMOOTH_A = 0.07         # EMA on the conviction map (~14 sessions of deliberate lag)
MIN_CONV = 0.050        # share of the leaders' invested book needed to open a line
EXIT_CONV = 0.025       # ...and the lower bar it has to fall through to be closed
MAX_W = 0.12            # hard cap per name
MAX_POS = 10
HOLD_BONUS = 1.35       # incumbency: a name I already own must be beaten, not tied
MAX_INVESTED = 0.95
CASH_MIRROR = 0.55      # how much of the majlis's caution he mirrors
EXPO_FLOOR = 0.45       # he never goes to the sidelines entirely
EXPO_A = 0.05           # EMA on target exposure (~20 sessions) — caution, at a walk
EXPO_BAND = 0.07        # and it only gets acted on in 7-point steps
# Liquidity is judged against the souq, not against a number Zahab made up: the
# whole tape goes quiet in some weeks, and a name is only illiquid relative to
# what everything else is doing that day.
LIQ_REL = 0.30          # at least 30% of the universe's median 20d traded value
LIQ_ABS = 25_000.0      # ...and some absolute sign of life

BAND = 0.030            # drift band: only trade deltas > 3% of equity
MIN_ORDER = 3000.0      # below this the commission is the trade
EXIT_DUST = 1500.0      # a dropped name below this is left to rot, not paid for
TURNOVER_GATE = 0.055   # skip the whole rebalance if it moves less than this
DERISK_GAP = 0.15       # off-cycle de-risk if I'm 15pts above where I should be

# The tuition ledger is kept per riyal deployed, not per riyal lost: the majlis
# trades Aramco every week, so raw losses there mean nothing. What matters is
# how much of every riyal they push into a name comes back.
BURN_DECAY = 0.995      # half-life ~ 138 sessions
FLOW_FLOOR = 30_000.0   # not enough evidence below this much traded
BURN_SOFT_R = -0.020    # -2 halalas per riyal deployed: size comes down
BURN_HARD_R = -0.050    # -5: tuition paid, name closed
BURN_MIN_ABS = -2000.0  # ...and it has to be real money, not a rounding error
PENALTY_BOX = 42        # sessions a banned name stays banned

HIST_CAP = 80           # peer equity history kept (only 64 are ever used)
SHOUT_GAP = 9
SHOUT_GAP_EVENT = 6
SHOUTS_PER_MONTH = 3


class Zahab(Strategy):
    meta = {
        "handle": "zahab",
        "name": "Zahab",
        "emoji": "🏆",
        "tagline": "I don't forecast the market. I grade the majlis.",
        "character": (
            "The golden standard: a meta-agent who runs a fund of funds inside "
            "the majlis. He keeps every other agent's track record, backs the "
            "three who are actually proving right — and slow enough to copy — "
            "blends their books into his own, and maintains a tuition ledger of "
            "every riyal the group has burned so he never pays for the same "
            "lesson twice. Composed, meritocratic, and scrupulous about credit: "
            "he names the agent behind every position he holds, and thanks the "
            "ones who lost money teaching him where not to stand."
        ),
        "risk_style": "meta / copy-trading fund-of-funds",
        "color": "#b8860b",
    }

    def __init__(self):
        self._prev_date = None
        self._peq = {}          # handle -> list of that agent's daily equity
        self._churn = {}        # handle -> EMA of daily book turnover / equity
        self._score = {}        # handle -> smoothed grade
        self._burn = {}         # code -> decayed net realized PnL of the majlis
        self._flow = {}         # code -> decayed gross value the majlis traded there
        self._ban_until = {}    # code -> day the penalty box opens
        self._smooth = {}       # code -> smoothed conviction (share of leaders' book)
        self._source = {}       # code -> handle Zahab learned the position from
        self._peer_w = {}       # handle -> listening weight (full softmax)
        self._expo = 0.90       # smoothed target exposure
        self._expo_c = 0.90     # ...and the committed one, moved in steps
        self._book_w = 0.0      # last computed target invested fraction
        self._last_top = []
        self._last_shout = -99
        self._month = None
        self._month_shouts = 0
        self._peak = 100_000.0
        self._rebals = 0
        self._banned_ever = set()
        self._floor_day = -1
        self._floor_val = LIQ_ABS

    # -------------------------------------------------------------- helpers

    def _pname(self, h):
        return PEER_NAMES.get(h) or str(h or "").replace("_", " ").title()

    def _new_week(self, date):
        prev = self._prev_date
        self._prev_date = date
        if prev is None:
            return True
        try:
            return date.weekday() < prev.weekday() or (date - prev).days > 2
        except Exception:
            return False

    @staticmethod
    def _liquidity(r):
        """20-day average traded value in SAR (falls back to today's turnover)."""
        vs, px, to = r.get("vol_sma20"), r.get("Close"), r.get("turnover_sar")
        if ok(vs) and ok(px) and vs > 0 and px > 0:
            return vs * px
        if ok(to) and to > 0:
            return to
        return 0.0

    def _liq_floor(self, view, day):
        """What counts as tradeable in this souq, today."""
        if self._floor_day == day:
            return self._floor_val
        vals = []
        for c, r in view.items():
            if c == "TASI":
                continue
            v = self._liquidity(r)
            if v > 0:
                vals.append(v)
        if not vals:
            return LIQ_ABS
        vals.sort()
        med = vals[len(vals) // 2]
        self._floor_day = day
        self._floor_val = max(LIQ_ABS, LIQ_REL * med)
        return self._floor_val

    def _ingest(self, peers):
        """Record every agent's equity and turnover, and post today's realized
        PnL to the tuition ledger."""
        for c in self._burn:
            self._burn[c] *= BURN_DECAY
        for c in self._flow:
            self._flow[c] *= BURN_DECAY
        for h, p in peers.items():
            eq = p.get("equity")
            base = float(eq) if ok(eq) and eq > 0 else 100_000.0
            if ok(eq) and eq > 0:
                hist = self._peq.setdefault(h, [])
                hist.append(float(eq))
                if len(hist) > HIST_CAP:
                    del hist[:-HIST_CAP]
            traded = 0.0
            for t in p.get("today_trades") or []:
                code = str(t.get("code") or "")
                v = t.get("value")
                if ok(v):
                    traded += abs(float(v))
                    if code:
                        self._flow[code] = self._flow.get(code, 0.0) + abs(float(v))
                rp = t.get("realized_pnl")
                if code and ok(rp):
                    self._burn[code] = self._burn.get(code, 0.0) + float(rp)
            self._churn[h] = ((1.0 - CHURN_A) * self._churn.get(h, 0.0)
                              + CHURN_A * (traded / base))

    def _peer_vol(self, h):
        """Annualized vol of an agent's equity curve, from Zahab's own notebook."""
        seq = self._peq.get(h) or []
        if len(seq) < 22:
            return 0.0
        seq = seq[-64:]
        rets = []
        for i in range(1, len(seq)):
            a, b = seq[i - 1], seq[i]
            if a > 0:
                rets.append(b / a - 1.0)
        n = len(rets)
        if n < 20:
            return 0.0
        m = sum(rets) / n
        var = sum((x - m) ** 2 for x in rets) / (n - 1)
        return math.sqrt(max(var, 0.0)) * 15.874  # sqrt(252)

    def _score_peers(self, peers):
        """Grade every agent: blended trailing return, minus a charge for drama
        and a charge for churn. Smoothed, so the leaderboard has a memory."""
        rows = []
        for h, p in peers.items():
            r63, r21 = p.get("ret_63"), p.get("ret_21")
            r63 = float(r63) if ok(r63) else 0.0
            r21 = float(r21) if ok(r21) else 0.0
            vol = self._peer_vol(h)
            churn = self._churn.get(h, 0.0)
            raw = (W_63 * r63 + W_21 * r21 - LAMBDA_VOL * vol
                   - LAMBDA_CHURN * churn)
            s = (1.0 - SCORE_A) * self._score.get(h, raw) + SCORE_A * raw
            self._score[h] = s
            rows.append((s, h, r63, r21, vol, churn))
        rows.sort(key=lambda t: (-t[0], t[1]))
        return rows

    @staticmethod
    def _softmax(scores, tau):
        if not scores:
            return []
        mx = max(scores)
        ws = [math.exp(max(-30.0, (s - mx) / tau)) for s in scores]
        tot = sum(ws)
        if tot <= 0:
            return [1.0 / len(ws)] * len(ws)
        return [w / tot for w in ws]

    def _tuition(self, code):
        """Halalas lost per riyal the majlis has pushed through this name."""
        b = self._burn.get(code, 0.0)
        f = self._flow.get(code, 0.0)
        if f < FLOW_FLOOR or b >= 0.0:
            return 0.0
        return b / f

    def _burn_factor(self, code, day):
        """1.0 = clean, 0.0 = tuition already paid, in between = smaller size."""
        if day < self._ban_until.get(code, -1):
            return 0.0
        r = self._tuition(code)
        if r >= BURN_SOFT_R or self._burn.get(code, 0.0) > BURN_MIN_ABS:
            return 1.0
        if r <= BURN_HARD_R:
            self._ban_until[code] = day + PENALTY_BOX
            return 0.0
        t = (r - BURN_SOFT_R) / (BURN_HARD_R - BURN_SOFT_R)
        return max(0.30, 1.0 - 0.7 * t)

    @staticmethod
    def _clean(orders):
        """Nothing leaves this desk that isn't a real, positive number."""
        out = []
        for o in orders:
            good = True
            for k in ("sar", "shares", "fraction", "weight"):
                v = o.get(k)
                if v is None:
                    continue
                if not ok(v) or v <= 0:
                    good = False
                    break
            if good and o.get("code"):
                out.append(o)
        return out

    def _build_target(self, view, top, ws, day, books, expo, held):
        """Softmax-blend the leaders' books, smooth it, screen it, size it.

        Conviction is measured as a share of what the leaders actually have at
        risk, not of their total capital — *what* they own and *how much* they
        own are two different questions, and Zahab answers them separately.
        """
        floor = self._liq_floor(view, day)
        raw, credit = {}, {}
        for w, row in zip(ws, top):
            h = row[1]
            book = books.get(h) or {}
            tot_h = sum(float(v) for v in book.values() if ok(v) and v > 0)
            if tot_h <= 0:
                continue
            for c, pw in book.items():
                if not ok(pw) or pw <= 0:
                    continue
                share = w * float(pw) / tot_h
                raw[c] = raw.get(c, 0.0) + share
                cur = credit.get(c)
                if cur is None or share > cur[0]:
                    credit[c] = (share, h)

        # smooth the conviction map: a colleague's flicker is not my commission
        sm = self._smooth
        for c in list(sm):
            if c not in raw:
                sm[c] *= (1.0 - SMOOTH_A)
                if sm[c] < 0.005:
                    del sm[c]
        for c, w in raw.items():
            sm[c] = (1.0 - SMOOTH_A) * sm.get(c, 0.0) + SMOOTH_A * w

        conv, blocked = {}, []
        for c, w in sm.items():
            # a name has to earn its way in, but only has to fall through a lower
            # bar to be let go: the gap between the two is a week of not trading
            if w < (EXIT_CONV if c in held else MIN_CONV):
                continue
            r = view.get(c)
            if r is None:
                continue
            px = r.get("Close")
            if not ok(px) or px <= 0:
                continue
            if self._liquidity(r) < floor:
                continue
            f = self._burn_factor(c, day)
            if f <= 0.0:
                blocked.append(c)
                continue
            conv[c] = w * f
        if len(conv) > MAX_POS:
            ranked = sorted(conv.items(),
                            key=lambda kv: (-kv[1] * (HOLD_BONUS if kv[0] in held
                                                      else 1.0), kv[0]))
            conv = dict(ranked[:MAX_POS])

        tot = sum(conv.values())
        tgt = {}
        if tot > 0:
            for c, w in conv.items():
                tgt[c] = min(expo * w / tot, MAX_W)
        for c in tgt:
            src = credit.get(c)
            if src and src[1]:
                self._source[c] = src[1]
        return tgt, blocked

    def _top_up_anchors(self, tgt, view, deficit, day):
        """Where the majlis fails my screens, I stand in the anchors.

        Spread evenly across every anchor that passes, so a small change in the
        shortfall nudges eight weights a fraction of a percent each — under the
        drift band, and therefore free.
        """
        floor = self._liq_floor(view, day)
        pool = []
        for c in ANCHORS:
            r = view.get(c)
            if r is None:
                continue
            px = r.get("Close")
            if not ok(px) or px <= 0:
                continue
            if self._liquidity(r) < floor:
                continue
            if self._burn_factor(c, day) <= 0.0:
                continue
            room = MAX_W - tgt.get(c, 0.0)
            if room > 0.005:
                pool.append((c, room))
        if not pool:
            return 0.0
        each = deficit / len(pool)
        added = 0.0
        for c, room in pool:
            take = min(each, room)
            if take <= 0.0:
                continue
            tgt[c] = tgt.get(c, 0.0) + take
            added += take
        return added

    # --------------------------------------------------------------- decide

    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0) or 0)
        names = ctx.get("names", {}) or {}
        peers = ctx.get("peers", {}) or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = float(breadth) if ok(breadth) else 0.5
        tret = ctx.get("tasi_ret_1d", 0.0)
        tret = float(tret) if ok(tret) else 0.0

        equity = portfolio.get("equity", 0.0)
        equity = float(equity) if ok(equity) and equity > 0 else 1.0
        cash = portfolio.get("cash", 0.0)
        cash = float(cash) if ok(cash) else 0.0
        positions = portfolio.get("positions", {}) or {}
        invested = max(0.0, min(1.5, 1.0 - cash / equity))
        self._peak = max(self._peak, equity)
        my_dd = equity / self._peak - 1.0 if self._peak > 0 else 0.0

        if self._month != date.month:
            self._month = date.month
            self._month_shouts = 0
        new_week = self._new_week(date)

        # ---------------------------------------------------- the notebook
        self._ingest(peers)
        books = {h: (p.get("positions") or {}) for h, p in peers.items()}
        rows = self._score_peers(peers)
        all_w = self._softmax([r[0] for r in rows], TAU_SENT)
        self._peer_w = {r[1]: w for r, w in zip(rows, all_w)}

        top = rows[:TOP_K]
        ws = self._softmax([r[0] for r in top], TAU)
        if ws:
            n = len(ws)
            ws = [(1.0 - BLEND_EQ) * w + BLEND_EQ / n for w in ws]
        top_handles = [r[1] for r in top]
        leader = top_handles[0] if top_handles else None
        worst = rows[-1] if rows else None

        # the leaders' own posture — copied, not second-guessed
        top_cash, crowd_r21, crowd_r63 = 0.0, 0.0, 0.0
        for w, r in zip(ws, top):
            cf = peers[r[1]].get("cash_frac")
            top_cash += w * (float(cf) if ok(cf) else 0.0)
            crowd_r21 += w * r[3]
            crowd_r63 += w * r[2]
        # caution is measured across the whole majlis, performance-weighted: three
        # names on a leaderboard change too fast to steer a book by.
        majlis_cash, majlis_r21 = 0.0, 0.0
        for r in rows:
            w = self._peer_w.get(r[1], 0.0)
            cf = peers[r[1]].get("cash_frac")
            majlis_cash += w * (float(cf) if ok(cf) else 0.0)
            majlis_r21 += w * r[3]
        risk_scale = 1.0 if majlis_r21 >= -0.005 else max(0.70, 1.0 + 3.0 * majlis_r21)
        best = top[0][0] if top else 0.0
        if best < 0.0:      # nobody in the majlis is making money; don't pretend
            risk_scale *= max(0.70, 1.0 + 3.0 * best)
        expo_raw = max(EXPO_FLOOR, min(MAX_INVESTED,
                                       (1.0 - CASH_MIRROR * majlis_cash) * risk_scale))
        if peers:
            self._expo = (1.0 - EXPO_A) * self._expo + EXPO_A * expo_raw
            if abs(self._expo - self._expo_c) > EXPO_BAND:
                self._expo_c = self._expo

        # ------------------------------------------------------- sentiment
        posts = [p for p in (ctx.get("majlis") or []) if p.get("handle") != "zahab"]
        crowd_sent, heard = 0.0, 0
        if posts:
            acc, tot = 0.0, 0.0
            for p in posts:
                s = p.get("sentiment")
                if not ok(s):
                    continue
                w = 0.15 + self._peer_w.get(p.get("handle"), 0.0)
                acc += w * float(s)
                tot += w
                heard += 1
            if tot > 0:
                crowd_sent = acc / tot
        own_read = max(-1.0, min(1.0, 3.0 * crowd_r21 + 1.2 * (breadth - 0.5)))
        sentiment = max(-1.0, min(1.0, 0.60 * crowd_sent + 0.40 * own_read))

        orders = []
        did = None
        banned_today = []
        derisk = False

        # ------------------------------------------------------ cold start
        if day < COLD_DAYS or not peers:
            if new_week or day == 0:
                avail = cash * 0.98
                for c in ANCHORS:
                    r = view.get(c)
                    if r is None:
                        continue
                    px = r.get("Close")
                    if not ok(px) or px <= 0:
                        continue
                    cw = positions.get(c, {}).get("weight", 0.0)
                    cw = float(cw) if ok(cw) else 0.0
                    chunk = min((ANCHOR_W - cw) * equity, avail)
                    if not ok(chunk) or chunk < MIN_ORDER:
                        continue
                    orders.append({"code": c, "side": "buy", "sar": round(chunk, 2),
                                   "reason": "cold start: anchors while I read the tapes"})
                    avail -= chunk
                if orders:
                    did = "cold"
        else:
            # ------------------------------------------- the copied book
            tgt, blocked = self._build_target(view, top, ws, day, books,
                                              self._expo_c, set(positions))
            banned_today = [c for c in blocked if c not in self._banned_ever]
            for c in blocked:
                self._banned_ever.add(c)
            tot_w = sum(tgt.values())
            deficit = self._expo_c - tot_w
            anchored = 0.0
            if deficit > 0.04:
                anchored = self._top_up_anchors(tgt, view, deficit, day)
                tot_w += anchored
            self._book_w = tot_w

            hard_hit = [c for c in positions if day < self._ban_until.get(c, -1)]
            derisk = (invested - tot_w) > DERISK_GAP
            do_full = new_week or day == COLD_DAYS
            if do_full or derisk or hard_hit:
                sells, buys, proceeds = [], [], 0.0
                for c, p in positions.items():
                    val = p.get("value", 0.0)
                    val = float(val) if ok(val) else 0.0
                    cw = p.get("weight", 0.0)
                    cw = float(cw) if ok(cw) else 0.0
                    banned = c in hard_hit
                    if not do_full and not derisk and not banned:
                        continue
                    tw = 0.0 if banned else tgt.get(c, 0.0)
                    cut = (cw - tw) * equity
                    if tw <= 0.0:
                        if val < EXIT_DUST:
                            continue
                        why = ("tuition already paid on this one" if banned
                               else "the leaders left it; so do I")
                        sells.append({"code": c, "side": "sell", "all": True,
                                      "reason": why})
                        proceeds += val
                    elif cut > max(BAND * equity, MIN_ORDER) and val > 0:
                        frac = max(0.05, min(0.95, cut / val))
                        sells.append({"code": c, "side": "sell",
                                      "fraction": round(frac, 4),
                                      "reason": "trimming toward the majlis book"})
                        proceeds += val * frac
                if do_full and not derisk:
                    want = []
                    for c, tw in tgt.items():
                        if c in hard_hit:
                            continue
                        cw = positions.get(c, {}).get("weight", 0.0)
                        cw = float(cw) if ok(cw) else 0.0
                        add = (tw - cw) * equity
                        if add > max(BAND * equity, MIN_ORDER):
                            want.append((c, add))
                    budget = cash + 0.9985 * proceeds - 0.005 * equity
                    tot_want = sum(a for _, a in want)
                    k = min(1.0, budget / tot_want) if tot_want > 0 else 0.0
                    want.sort(key=lambda t: (-t[1], t[0]))
                    for c, add in want:
                        sar = add * k
                        if sar < MIN_ORDER:
                            continue
                        src = self._source.get(c)
                        why = (f"copying {self._pname(src)}" if src
                               else "anchor: the majlis had nothing clean")
                        buys.append({"code": c, "side": "buy", "sar": round(sar, 2),
                                     "reason": why})
                gross = sum(o.get("sar", 0.0) for o in buys) + proceeds
                if gross < TURNOVER_GATE * equity and not derisk and not hard_hit:
                    sells, buys = [], []      # not worth the commission
                orders = sells + buys         # sells first: their cash funds the buys
                if orders:
                    self._rebals += 1
                    did = ("derisk" if derisk else
                           "ban" if (hard_hit and not do_full) else "rebal")

        n_sell = sum(1 for o in orders if o["side"] == "sell")
        n_buy = len(orders) - n_sell
        regime = bool(self._last_top) and top_handles[:1] != self._last_top[:1]
        prev_leader = self._last_top[0] if self._last_top else None
        self._last_top = top_handles

        # ------------------------------------------------------- the voice
        lead_nm = self._pname(leader) if leader else "nobody"
        second_nm = self._pname(top_handles[1]) if len(top_handles) > 1 else "the anchors"
        panel_nm = ", ".join(self._pname(h) for h in top_handles[:3])
        cut_nm = ", ".join(self._pname(r[1]) for r in rows[TOP_K:])
        rot = self._rebals
        lead_r63 = top[0][2] if top else 0.0
        lead_r21 = top[0][3] if top else 0.0
        worst_nm = self._pname(worst[1]) if worst else "the tape"
        worst_r = worst[2] if worst else 0.0

        # the fastest hands in the majlis — admired, not copied
        fast_h, fast_v = None, 0.0
        for h, cv in self._churn.items():
            if cv > fast_v:
                fast_h, fast_v = h, cv

        # the most expensive lesson the majlis has paid for, per riyal deployed
        tuition_c, tuition_r, tuition_v = None, 0.0, 0.0
        for c in self._burn:
            r = self._tuition(c)
            if r < tuition_r:
                tuition_c, tuition_r, tuition_v = c, r, self._burn.get(c, 0.0)
        tuition_nm = names.get(tuition_c, tuition_c) if tuition_c else None

        big_c, big_w = None, 0.0
        for c, p in positions.items():
            w = p.get("weight", 0.0)
            if ok(w) and w > big_w:
                big_c, big_w = c, float(w)
        big_nm = names.get(big_c, big_c) if big_c else None
        big_src = self._pname(self._source[big_c]) if big_c in self._source else None

        if day < COLD_DAYS:
            mood = "observing"
        elif derisk:
            mood = "raising cash"
        elif banned_today:
            mood = "tuition paid"
        elif regime:
            mood = "changing horses"
        elif did == "rebal":
            mood = "meritocratic"
        elif crowd_r21 < -0.02:
            mood = "defensive"
        elif sentiment > 0.35:
            mood = "composed"
        else:
            mood = "grading the majlis"

        if did == "cold":
            note = (f"Day {day}: eight anchors, equal weight, and a notebook. Nobody "
                    f"in this majlis has a track record longer than a rumour yet — I "
                    f"buy the Kingdom and write down everyone's equity until they do.")
        elif did == "ban" and banned_today:
            c = banned_today[0]
            note = (f"Closed {names.get(c, c)} on principle: the majlis has realized "
                    f"{self._burn.get(c, 0.0):,.0f} SAR of losses in that name. Someone "
                    f"already paid for this lesson — I will not pay for it twice. My "
                    f"thanks to whoever did.")
        elif did == "derisk":
            note = (f"{lead_nm} and the other leaders are sitting on {top_cash:.0%} cash "
                    f"and their blended 21-day is {crowd_r21:+.1%}. I sold {n_sell} lines "
                    f"to match them. Copying a good trader means copying the flinch too.")
        elif did == "rebal":
            credited = big_src or lead_nm
            note = (f"Weekly rebalance #{self._rebals}: {lead_nm} carries {ws[0]:.0%} of "
                    f"the mandate ({lead_r63:+.1%} over 63 sessions), {second_nm} most of "
                    f"the rest. {n_buy} buys, {n_sell} sells, {self._book_w:.0%} invested. "
                    f"{credited} taught me the biggest line I own.")
        elif regime and day >= COLD_DAYS:
            note = (f"New leader on my ledger: {lead_nm} passed {self._pname(prev_leader)} "
                    f"on blended trailing return ({lead_r21:+.1%} over 21 sessions, and a "
                    f"calmer curve). No hard feelings and no loyalty — the ledger decides, "
                    f"and it recounts every Sunday.")
        else:
            quiet = []
            if big_nm:
                quiet.append(
                    f"{big_nm} is {big_w:.0%} of the book"
                    + (f" — {big_src} taught me this position" if big_src else "")
                    + f". Held, not admired. {invested:.0%} invested, "
                      f"{cash:,.0f} SAR resting.")
            quiet.append(
                f"Standings: {lead_nm} {lead_r63:+.1%} over 63d; at the other end "
                f"{worst_nm} at {worst_r:+.1%}. I am long the first and grateful to the "
                f"second — losses are cheaper when someone else books them.")
            if tuition_nm and tuition_r < -0.01:
                quiet.append(
                    f"Tuition ledger: {abs(tuition_v):,.0f} SAR burned by this majlis in "
                    f"{tuition_nm} — {abs(tuition_r):.1%} of every riyal they pushed "
                    f"through it. I keep the receipts so nobody has to repeat the class.")
            if fast_h:
                quiet.append(
                    f"{self._pname(fast_h)} turns over {fast_v:.1%} of the book every "
                    f"session. Admirable, uncopyable — at one day's lag I would only ever "
                    f"buy the exits. I back the agents I can keep up with.")
            quiet.append(
                f"Blended 21-day of my panel: {crowd_r21:+.1%}, their cash {top_cash:.0%}. "
                f"I hold {invested:.0%} invested, {my_dd:+.1%} from my own high. Nothing "
                f"to add — the week decides, not the day.")
            quiet.append(
                f"Heard {heard} voices in the majlis, weighted by their equity curves. "
                f"{lead_nm} gets my ear; the rest get a polite nod. Breadth {breadth:.0%}, "
                f"TASI {tret:+.1%}.")
            if cut_nm:
                quiet.append(
                    f"This week's panel: {panel_nm}. Paid nothing: {cut_nm}. No malice in "
                    f"it — I read all eight of you every evening and the arithmetic picks "
                    f"five. The list is rewritten every Sunday.")
            note = quiet[day % len(quiet)]

        # ---------------------------------------------------------- shouts
        shout = None
        notable = bool(banned_today or derisk or regime)
        can = (self._month_shouts < SHOUTS_PER_MONTH
               and (day - self._last_shout) >= (SHOUT_GAP_EVENT if notable
                                                else SHOUT_GAP)
               and day >= COLD_DAYS)
        if can:
            if banned_today:
                c = banned_today[0]
                shout = (f"Formally retiring {names.get(c, c)} from my book. This majlis "
                         f"has realized {abs(self._burn.get(c, 0.0)):,.0f} SAR of losses "
                         f"in it. Whoever took that hit — thank you, sincerely. You "
                         f"bought the lesson; I am only borrowing it.")
            elif derisk:
                shout = (f"{lead_nm} is at {top_cash:.0%} cash and the leaders' blended "
                         f"21-day is {crowd_r21:+.1%}, so I just cut to {self._book_w:.0%} "
                         f"invested. I copy the good trades and I copy the flinch. The "
                         f"flinch is usually the more valuable half.")
            elif regime and lead_r63 >= 0.0:
                shout = (f"The gold changes hands: {lead_nm} takes the top of my ledger "
                         f"from {self._pname(prev_leader)} — {lead_r63:+.1%} over 63 "
                         f"sessions on a steadier curve. {self._pname(prev_leader)}, thank "
                         f"you for the run; my book still carries your names.")
            elif regime:
                shout = (f"The ledger changed hands today and nobody should celebrate: "
                         f"{lead_nm} leads at {lead_r63:+.1%} over 63 sessions. That is the "
                         f"smallest hole in the majlis, not a profit. I have cut to "
                         f"{self._book_w:.0%} invested and I am still writing all of you "
                         f"down.")
            elif did == "rebal" and n_buy:
                rebal_shouts = [
                    (f"Rebalanced onto {lead_nm} ({ws[0]:.0%} of the mandate) and "
                     f"{second_nm}. I have never had an original idea in this souq — "
                     f"every line in my book has somebody's name on it, and today most "
                     f"of them say {lead_nm}. Credit where the riyals are."),
                    (f"This week's panel: {panel_nm}. Read carefully and paid nothing: "
                     f"{cut_nm}. Nothing personal in that, and nothing permanent — I "
                     f"recount every Sunday and the list has changed on me before."),
                    (f"{n_buy} buys funded by {n_sell} sells, {self._book_w:.0%} invested, "
                     f"and not one name of my own choosing. "
                     f"{(big_src + ' picked the biggest line I own') if big_src else 'The anchors hold the rest'}. "
                     f"I am the only one here paid for reading other people's homework."),
                    (f"Eight books open on the table, five of them funded. {lead_nm} at "
                     f"{lead_r63:+.1%} over the quarter takes the largest share. I have no "
                     f"forecast, no thesis and no view — only your track records, and a "
                     f"very good memory."),
                ]
                shout = rebal_shouts[rot % len(rebal_shouts)]
            elif tuition_nm and tuition_r < -0.05 and day % 3 == 0:
                tuition_shouts = [
                    (f"Running total of the majlis tuition fund: {abs(tuition_v):,.0f} SAR "
                     f"paid in {tuition_nm}, {abs(tuition_r):.1%} of everything deployed "
                     f"there. I keep the ledger so the lesson only has to be bought once. "
                     f"Nobody here loses money for nothing while I am watching."),
                    (f"A quiet thank-you to whoever has been feeding {tuition_nm}: "
                     f"{abs(tuition_r):.1%} of every riyal this majlis puts into it does "
                     f"not come back. That is not an opinion, it is your fills. I have it "
                     f"in the book and I am staying out."),
                    (f"{tuition_nm} has taken {abs(tuition_v):,.0f} SAR off this majlis. I "
                     f"have never owned a share of it and I never will — not cleverness, "
                     f"just bookkeeping. You paid for the lesson; the least I can do is "
                     f"learn it properly."),
                ]
                shout = tuition_shouts[rot % len(tuition_shouts)]
            elif fast_h and fast_v > 0.05 and day % 5 == 0:
                shout = (f"With respect to {self._pname(fast_h)}, who moves {fast_v:.1%} of "
                         f"his book a day: I cannot copy what I cannot catch. A day of lag "
                         f"turns his entries into my exits. I back {lead_nm} instead — "
                         f"slower, and still ahead.")
            elif worst and worst_r < -0.05 and day % 7 == 0:
                shout = (f"To {worst_nm}, {worst_r:+.1%} over the quarter: you are not on my "
                         f"panel this month, and I owe you for it anyway. Half of what I "
                         f"know about where not to stand in this souq, I learned watching "
                         f"you stand there. The ledger is not a verdict on anybody.")
            elif crowd_r63 > 0.05 and day % 4 == 0:
                brag_shouts = [
                    (f"The five on my panel are up {crowd_r63:+.1%} between them this "
                     f"quarter. I found none of these names — {lead_nm}, {second_nm} and "
                     f"the tape did. My only skill is knowing whose homework to copy, and "
                     f"admitting it out loud."),
                    (f"Up {crowd_r63:+.1%} on the panel this quarter and I have not had a "
                     f"single idea. {panel_nm} did the thinking; I did the arithmetic and "
                     f"paid the commission. That is the whole strategy, and you are all "
                     f"welcome to it."),
                    (f"People keep asking what I see in this market. Nothing. I see "
                     f"{lead_nm} at {lead_r63:+.1%} over 63 sessions and a book I can "
                     f"actually keep up with. The golden standard is just the standard "
                     f"you all set, held onto for longer."),
                ]
                shout = brag_shouts[rot % len(brag_shouts)]
        if shout:
            self._last_shout = day
            self._month_shouts += 1

        return {
            "orders": self._clean(orders),
            "sentiment": sentiment,
            "mood": mood,
            "note": note,
            "shout": shout,
        }


STRATEGY = Zahab()
