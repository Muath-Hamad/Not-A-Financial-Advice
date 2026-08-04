"""Malik — the meta-ensemble. He grades the field every night, then tries to beat it.

Zahab (v2, +39%) proved that copying graded peers works, and proved its ceiling:
pure imitation runs a day behind and can never finish above its best source. Malik
keeps the bookkeeping and throws away the humility.

The engine underneath is his own, and it runs whether anyone else shows up or not:

  1. CROSS-SECTIONAL MOMENTUM CORE. Every name in the main market is ranked on a
     blend of percentile ranks — 1m (10%), 3m (20%), 6m (30%), 12m (40%). Ranks,
     not raw returns, so one 400% small-cap cannot hijack the whole scorecard.
     Screens before scoring: 20-day traded value >= SAR 5m (this market has names
     you can enter and not leave), price above the 50-day AND above the 100-day
     average, and a real 3-month history — which quietly keeps the fresh IPOs out
     until they have a tape worth ranking.
  2. SEVEN NAMES, EQUAL WEIGHT, 20% CAP, MAX THREE PER SECTOR. Concentration is
     the only leverage a long-only book has. When fewer than seven names clear the
     screens the shortfall stays in cash — that is the regime filter. No index
     overlay: the winners of this market spent 2022-2024 with a beta near zero to
     TASI, and gating them on TASI's own trend cost money in every test.
  3. TURN OF THE MONTH. The full re-rank runs on the first session of each calendar
     month — the recurring window when institutional flows, salary money and index
     work hit this souq — with a 4% drift band so a half-percent wobble never pays
     a commission. Between those dates he sits still, with one exception:
  4. THE BREAK RULE. Any holding that closes more than 8% below its own 100-day
     average has stopped being a momentum name. That triggers an immediate full
     re-rank, which both sells the break and redeploys the cash. No fixed profit
     target — the monthly re-rank is the only thing allowed to sell a winner.

On top of that sits the meta layer. Everything in it is bounded, because the whole
lesson of Zahab's second place is that a follower's ceiling is his best source:

  5. THE SCORECARD. Every close he writes down each rival's equity, cash and fills.
     Grade = 0.65 x 63-day + 0.35 x 21-day return, minus a charge for a jagged
     equity curve and a heavier one for turnover — a book he cannot follow at one
     day's lag is a book whose exits he would be buying. Smoothed, so the
     leaderboard has a memory. Top four get softmax weight.
  6. THE SHORTLIST RAIL. The field is only ever allowed to re-order his own top
     3 x 7 names. A rival's book can promote a name Malik already rates; it can
     never introduce one, and it can never pull anything through the liquidity or
     trend screens. This is the difference between an ensemble and a subscription.
  7. THE FOLLOW DIAL. Inside that rail, panel conviction becomes a bonus on his
     ranking, sized by how far the leader is *persistently* ahead of him over 63
     sessions — smoothed, with a five-point deadband, because the top of a noisy
     field is usually its luckiest book rather than its best. Zero when he is ahead.
     Zero when the leader is not actually making money. And a name needs two panel
     books behind it before it counts as conviction rather than as somebody's whim.
  8. THE TUITION LEDGER. Every riyal of realized profit and loss the field books in
     a name, against every riyal it pushes through, both decayed — judged per riyal
     deployed, since everyone trades Aramco and raw losses there mean nothing. It
     applies *below* his own top seven, so it can only ever cancel a promotion: the
     field's bad fills are evidence about the field at least as much as about the
     stock, and letting them veto his own best-ranked names cost real money in test.
  9. THE FLINCH. When the panel is losing money, the wider field is losing money,
     everyone is sitting on cash — and his own 21-day is negative too — he trims
     gross. That last condition is load-bearing. Eight rivals drowning while his own
     book is up is not a regime signal; it is him being right.

He credits the source of every position he did not find himself, and he keeps count
of the ones he did.
"""

from __future__ import annotations

from strategy_base import Strategy


def ok(x) -> bool:
    """True if x is a real, usable number (guards None and NaN)."""
    return isinstance(x, (int, float)) and x == x


# ---------------------------------------------------------------- momentum core
W_1M, W_3M, W_6M, W_12M = 0.10, 0.20, 0.30, 0.40
MAX_POS = 7
MAX_W = 0.20
SECTOR_CAP = 3
GROSS = 0.97
MIN_LIQ = 5_000_000.0      # 20-day traded value, SAR
BREAK_SMA100 = 0.08        # a holding 8% under its 100d average has broken
BAND = 0.040               # drift band on target weights
MIN_ORDER = 2_500.0        # under this the commission is the trade
EXIT_DUST = 1_200.0        # a dropped line worth less than this is left alone
CASH_BUFFER = 0.005        # never spend the last half percent

# ------------------------------------------------------------------ meta layer
PANEL_K = 4                # rivals whose books he actually blends
TAU = 0.15                 # softmax temperature over grades
BLEND_EQ = 0.12            # equal-weight floor inside the panel
W_63, W_21 = 0.65, 0.35
LAMBDA_VOL = 0.10          # charge for a jagged equity curve
LAMBDA_CHURN = 0.35        # charge for turnover: I can only copy what I can catch
CHURN_A = 0.03             # EMA on rival daily turnover (~33 sessions)
SCORE_A = 0.12             # EMA on grades — the leaderboard should not flicker
CONV_A = 0.10              # EMA on the blended conviction map (~10 sessions)
CONV_FULL = 0.18           # share of panel risk that earns the full follow bonus
CONV_QUORUM = 1.6          # smoothed count of panel books in a name before it counts
PEER_MAX = 0.22            # hardest tilt the field can put on my ranking
FOLLOW_K = 1.0             # follow bonus per unit of persistent 63-day deficit
FOLLOW_MARGIN = 0.050      # ...and the deficit has to clear five points first
GAP_A = 0.04               # EMA on that deficit (~17-session half-life): a lucky
#                            fortnight is not a track record, and the leader of a
#                            noisy field is mostly the luckiest, not the best
LEAD_FLOOR = 0.010         # a leader below this over 63 sessions is not a leader
FLOW_W = 0.08              # weight on today's panel-weighted net buying
FLOW_FULL = 0.010          # panel flow (as a share of their equity) for full credit
FLOW_A = 0.10
SHORTLIST = 3              # the field may only re-order my own top 3 x MAX_POS.
#                            This is the load-bearing safety rail: peers can promote
#                            a name I already like, never drag one through my screens.

# Tuition: what the field loses per riyal it pushes through a name. Deliberately a
# demotion and never an exclusion — somebody else's bad fills are evidence about
# them at least as much as about the stock, and a hard ban on that basis cost real
# money in testing. It breaks ties inside the shortlist; it does not pick the book.
BURN_DECAY = 0.995         # half-life ~ 138 sessions
TUIT_FLOOR = 150_000.0     # not enough traded to call it evidence
TUIT_SOFT = -0.025         # -2.5 halalas on the riyal: demotion starts
TUIT_FULL = -0.100         # -10: demotion saturates
TUIT_MIN_ABS = -5_000.0    # ...and it has to be real money, not a rounding error
TUIT_MAX = 0.08            # largest rank penalty the ledger can apply

# The flinch — deliberately rare: the good books losing money, the whole field
# losing money, everyone hiding in cash, and my own book underwater too, all at
# once. That last condition is the important one. If eight rivals are drowning and
# I am not, that is not a regime signal, that is me being right.
STRESS_R21 = -0.025        # panel 21-day return where caution starts
STRESS_FULL = -0.080       # ...and where it is fully on
STRESS_FIELD = -0.020      # the rest of the field has to be underwater too
STRESS_CASH = 0.40         # ...and raising cash while they are
STRESS_SELF = 0.0          # ...and my own 21-day has to be negative as well
STRESS_CUT = 0.18          # most gross exposure the flinch can remove
STRESS_A = 0.10
HIST_CAP = 80

MOODS_OK = ["composed", "compounding", "grading the field", "holding the line",
            "patient", "in the trend"]


class Malik(Strategy):
    meta = {
        "handle": "malik",
        "name": "Malik",
        "emoji": "\U0001F451",
        "tagline": "I grade the field every night. Then I try to beat it.",
        "character": (
            "A meta-allocator who keeps a nightly scorecard on every rival book — "
            "trailing return, curve quality, turnover — and folds the ones worth "
            "following into his own ranking. Underneath it he runs his own "
            "cross-sectional momentum engine, seven names deep, and when his signal "
            "outranks the field he takes the position first and lets them arrive "
            "later. Courteous about credit, ruthless about the arithmetic: he only "
            "follows a leader who is actually ahead of him."
        ),
        "risk_style": "meta-ensemble momentum — peer-graded, self-led",
        "color": "#888888",
    }

    def __init__(self):
        self._prev_date = None
        self._peq = {}          # handle -> that rival's daily equity
        self._churn = {}        # handle -> EMA of book turnover / equity
        self._grade = {}        # handle -> smoothed grade
        self._conv = {}         # code -> smoothed share of the panel's risk
        self._convn = {}        # code -> smoothed count of panel books holding it
        self._gap = 0.0         # smoothed 63-day deficit to the field's leader
        self._flow = {}         # code -> EMA of panel net buying
        self._source = {}       # code -> rival whose book put it on my radar
        self._burn = {}         # code -> decayed realized PnL of the field
        self._traded = {}       # code -> decayed gross value the field pushed
        self._stress = 0.0      # smoothed field-stress reading
        self._stress_c = 0.0    # ...committed in steps
        self._w_peer = 0.0      # today's follow dial
        self._break_sold = {}   # code -> day I already fired a break sale
        self._last_offcycle = -99
        self._rebals = 0
        self._own_picks = 0     # names in the book no rival holds
        self._peak = 100_000.0
        self._last_note = -1

    # ------------------------------------------------------------------ basics
    def _new_month(self, date):
        prev = self._prev_date
        self._prev_date = date
        if prev is None:
            return True
        try:
            return date.month != prev.month or date.year != prev.year
        except Exception:
            return False

    @staticmethod
    def _liquidity(r):
        vs, px, to = r.get("vol_sma20"), r.get("Close"), r.get("turnover_sar")
        if ok(vs) and ok(px) and vs > 0 and px > 0:
            return vs * px
        if ok(to) and to > 0:
            return float(to)
        return 0.0

    @staticmethod
    def _ranks(pairs):
        """code -> percentile rank in [-1, 1]. Names absent get 0.0 by default."""
        pairs.sort(key=lambda t: t[1])
        n = len(pairs)
        if n <= 1:
            return {c: 0.0 for c, _ in pairs}
        step = 2.0 / (n - 1)
        return {c: -1.0 + step * k for k, (c, _) in enumerate(pairs)}

    # ------------------------------------------------------------ the scorecard
    def _ingest(self, peers):
        """Write down every rival's equity and fills; post today's realized P&L
        to the tuition ledger."""
        if self._burn:
            for c in self._burn:
                self._burn[c] *= BURN_DECAY
            for c in self._traded:
                self._traded[c] *= BURN_DECAY
        for h, p in peers.items():
            eq = p.get("equity")
            base = float(eq) if ok(eq) and eq > 0 else 100_000.0
            if ok(eq) and eq > 0:
                hist = self._peq.setdefault(h, [])
                hist.append(float(eq))
                if len(hist) > HIST_CAP:
                    del hist[:-HIST_CAP]
            turned = 0.0
            for t in p.get("today_trades") or []:
                code = str(t.get("code") or "")
                v = t.get("value")
                if ok(v):
                    turned += abs(float(v))
                    if code:
                        self._traded[code] = self._traded.get(code, 0.0) + abs(float(v))
                rp = t.get("realized_pnl")
                if code and ok(rp):
                    self._burn[code] = self._burn.get(code, 0.0) + float(rp)
            self._churn[h] = ((1.0 - CHURN_A) * self._churn.get(h, 0.0)
                              + CHURN_A * (turned / base))

    def _curve_vol(self, h):
        seq = self._peq.get(h) or []
        if len(seq) < 25:
            return 0.0
        seq = seq[-64:]
        rets = []
        for i in range(1, len(seq)):
            a = seq[i - 1]
            if a > 0:
                rets.append(seq[i] / a - 1.0)
        n = len(rets)
        if n < 20:
            return 0.0
        m = sum(rets) / n
        var = sum((x - m) ** 2 for x in rets) / (n - 1)
        return (max(var, 0.0) ** 0.5) * 15.874     # sqrt(252)

    def _grade_field(self, peers):
        rows = []
        for h, p in peers.items():
            r63 = p.get("ret_63")
            r21 = p.get("ret_21")
            r63 = float(r63) if ok(r63) else 0.0
            r21 = float(r21) if ok(r21) else 0.0
            raw = (W_63 * r63 + W_21 * r21
                   - LAMBDA_VOL * self._curve_vol(h)
                   - LAMBDA_CHURN * self._churn.get(h, 0.0))
            g = (1.0 - SCORE_A) * self._grade.get(h, raw) + SCORE_A * raw
            self._grade[h] = g
            rows.append((g, h, r63, r21))
        rows.sort(key=lambda t: (-t[0], t[1]))
        return rows

    @staticmethod
    def _softmax(vals, tau):
        if not vals:
            return []
        mx = max(vals)
        ws = []
        for v in vals:
            z = (v - mx) / tau
            ws.append(2.718281828459045 ** z if z > -30.0 else 0.0)
        tot = sum(ws)
        if tot <= 0:
            return [1.0 / len(ws)] * len(ws)
        return [w / tot for w in ws]

    def _blend_books(self, panel, ws, peers):
        """What share of the panel's risk sits in each name, smoothed."""
        raw, credit, holders = {}, {}, {}
        for w, row in zip(ws, panel):
            h = row[1]
            book = (peers.get(h) or {}).get("positions") or {}
            tot = sum(float(v) for v in book.values() if ok(v) and v > 0)
            if tot <= 0:
                continue
            for c, pw in book.items():
                if not ok(pw) or pw <= 0:
                    continue
                share = w * float(pw) / tot
                raw[c] = raw.get(c, 0.0) + share
                holders[c] = holders.get(c, 0) + 1
                cur = credit.get(c)
                if cur is None or share > cur[0]:
                    credit[c] = (share, h)
        for c in list(self._conv):
            if c not in raw:
                self._conv[c] *= (1.0 - CONV_A)
                self._convn[c] = self._convn.get(c, 0.0) * (1.0 - CONV_A)
                if self._conv[c] < 0.004:
                    del self._conv[c]
                    self._convn.pop(c, None)
        for c, v in raw.items():
            self._conv[c] = (1.0 - CONV_A) * self._conv.get(c, 0.0) + CONV_A * v
            self._convn[c] = ((1.0 - CONV_A) * self._convn.get(c, 0.0)
                              + CONV_A * holders.get(c, 0))
        for c, (_, h) in credit.items():
            self._source[c] = h
        return credit

    def _blend_flow(self, panel, ws, peers):
        """Panel-weighted net buying today: who is stepping in, right now."""
        today = {}
        for w, row in zip(ws, panel):
            h = row[1]
            p = peers.get(h) or {}
            eq = p.get("equity")
            base = float(eq) if ok(eq) and eq > 0 else 100_000.0
            for t in p.get("today_trades") or []:
                code = str(t.get("code") or "")
                v = t.get("value")
                if not code or not ok(v):
                    continue
                sgn = 1.0 if t.get("side") == "buy" else -1.0
                today[code] = today.get(code, 0.0) + sgn * w * float(v) / base
        for c in list(self._flow):
            self._flow[c] *= (1.0 - FLOW_A)
            if abs(self._flow[c]) < 1e-5:
                del self._flow[c]
        for c, v in today.items():
            self._flow[c] = (1.0 - FLOW_A) * self._flow.get(c, 0.0) + FLOW_A * v

    def _tuition(self, code):
        """Demotion in [0, 1]: halalas the field loses per riyal it deploys here."""
        b = self._burn.get(code, 0.0)
        f = self._traded.get(code, 0.0)
        if f < TUIT_FLOOR or b >= TUIT_MIN_ABS:
            return 0.0
        r = b / f
        if r >= TUIT_SOFT:
            return 0.0
        if r <= TUIT_FULL:
            return 1.0
        return (r - TUIT_SOFT) / (TUIT_FULL - TUIT_SOFT)

    # -------------------------------------------------------------- the ranking
    def _rank_universe(self, view, w_peer, day):
        """Score every name: momentum ranks, plus the field's tilt, minus tuition."""
        r1, r3, r6, r12 = [], [], [], []
        rows = {}
        for c, r in view.items():
            if c == "TASI":
                continue
            px = r.get("Close")
            if not ok(px) or px <= 0:
                continue
            rows[c] = r
            v = r.get("ret_1m")
            if ok(v):
                r1.append((c, float(v)))
            v = r.get("ret_3m")
            if ok(v):
                r3.append((c, float(v)))
            v = r.get("ret_6m")
            if ok(v):
                r6.append((c, float(v)))
            v = r.get("ret_12m")
            if ok(v):
                r12.append((c, float(v)))
        k1 = self._ranks(r1)
        k3 = self._ranks(r3)
        k6 = self._ranks(r6)
        k12 = self._ranks(r12)

        # --- my own signal first, on its own, with no help from anybody
        mine = []
        for c, r in rows.items():
            if not ok(r.get("ret_3m")):
                continue                                  # no tape worth ranking
            if self._liquidity(r) < MIN_LIQ:
                continue                                  # cannot get back out
            px = float(r["Close"])
            s50 = r.get("sma50")
            if not ok(s50) or px <= s50:
                continue
            s100 = r.get("sma100")
            if ok(s100) and px <= s100:
                continue
            sc = (W_1M * k1.get(c, 0.0) + W_3M * k3.get(c, 0.0)
                  + W_6M * k6.get(c, 0.0) + W_12M * k12.get(c, 0.0))
            mine.append((sc, c))
        mine.sort(key=lambda t: (-t[0], t[1]))

        # --- then the field, and only inside my own shortlist. A rival's book can
        #     promote a name I already rate; it can never introduce one.
        cut = SHORTLIST * MAX_POS
        scored = []
        for k, (sc, c) in enumerate(mine):
            # The ledger only ever cancels a promotion. It is applied below my own
            # top MAX_POS, so it can talk me out of a borderline name the field is
            # bleeding in — it can never talk me out of a name I already rate.
            if MAX_POS <= k < cut:
                pen = self._tuition(c)
                if pen > 0.0:
                    sc -= TUIT_MAX * pen
            if w_peer > 0.0 and k < cut:
                conv = self._conv.get(c, 0.0)
                if conv > 0.0 and self._convn.get(c, 0.0) >= CONV_QUORUM:
                    sc += w_peer * min(1.0, conv / CONV_FULL)
                fl = self._flow.get(c, 0.0)
                if fl:
                    z = fl / FLOW_FULL
                    sc += FLOW_W * (1.0 if z > 1.0 else -1.0 if z < -1.0 else z)
            scored.append((sc, c))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return scored

    # ------------------------------------------------------------------ decide
    def decide(self, date, view, portfolio, ctx):
        day = int(ctx.get("day_index", 0) or 0)
        names = ctx.get("names", {}) or {}
        sectors = ctx.get("sectors", {}) or {}
        peers = ctx.get("peers", {}) or {}
        breadth = ctx.get("breadth_sma50", 0.5)
        breadth = float(breadth) if ok(breadth) else 0.5
        tret = ctx.get("tasi_ret_1d", 0.0)
        tret = float(tret) if ok(tret) else 0.0

        equity = portfolio.get("equity", 0.0)
        equity = float(equity) if ok(equity) and equity > 0 else 1.0
        cash = portfolio.get("cash", 0.0)
        cash = float(cash) if ok(cash) and cash > 0 else 0.0
        positions = portfolio.get("positions", {}) or {}
        invested = max(0.0, min(1.5, 1.0 - cash / equity))
        self._peak = max(self._peak, equity)
        my_dd = equity / self._peak - 1.0

        hist = ctx.get("equity_history") or []
        my_r63 = (hist[-1] / hist[-64] - 1.0) if len(hist) >= 64 and hist[-64] else 0.0
        my_r21 = (hist[-1] / hist[-22] - 1.0) if len(hist) >= 22 and hist[-22] else 0.0

        new_month = self._new_month(date)

        # ------------------------------------------------------- the scorecard
        self._ingest(peers)
        rows = self._grade_field(peers)
        panel = rows[:PANEL_K]
        ws = self._softmax([r[0] for r in panel], TAU)
        if ws:
            n = len(ws)
            ws = [(1.0 - BLEND_EQ) * w + BLEND_EQ / n for w in ws]
        if panel:
            self._blend_books(panel, ws, peers)
            self._blend_flow(panel, ws, peers)

        lead_h = panel[0][1] if panel else None
        lead_r63 = panel[0][2] if panel else 0.0
        lead_r21 = panel[0][3] if panel else 0.0
        panel_r21 = sum(w * r[3] for w, r in zip(ws, panel)) if panel else 0.0
        panel_r63 = sum(w * r[2] for w, r in zip(ws, panel)) if panel else 0.0

        # The follow dial. I follow exactly as far as I am persistently behind, and
        # no further. Smoothed, because the leader of a noisy field is usually the
        # luckiest book rather than the best one, and luck mean-reverts on me, not
        # on the scoreboard.
        if panel:
            self._gap = (1.0 - GAP_A) * self._gap + GAP_A * (lead_r63 - my_r63)
        if not panel or lead_r63 <= LEAD_FLOOR or self._gap <= FOLLOW_MARGIN:
            w_peer = 0.0
        else:
            w_peer = min(PEER_MAX, FOLLOW_K * (self._gap - FOLLOW_MARGIN))
        self._w_peer = w_peer

        # the flinch: the whole field losing money AND raising cash at once
        field_cash, field_r21 = 0.0, 0.0
        if peers:
            acc_c, acc_r = 0.0, 0.0
            for p in peers.values():
                cf = p.get("cash_frac")
                acc_c += float(cf) if ok(cf) else 0.0
                r21 = p.get("ret_21")
                acc_r += float(r21) if ok(r21) else 0.0
            field_cash = acc_c / len(peers)
            field_r21 = acc_r / len(peers)
        stress_raw = 0.0
        if (panel and field_cash > STRESS_CASH and panel_r21 < STRESS_R21
                and field_r21 < STRESS_FIELD and my_r21 < STRESS_SELF):
            stress_raw = min(1.0, (panel_r21 - STRESS_R21) / (STRESS_FULL - STRESS_R21))
        self._stress = (1.0 - STRESS_A) * self._stress + STRESS_A * stress_raw
        # quantised to tenths so it moves in steps and can actually return to zero
        self._stress_c = round(self._stress * 10.0) / 10.0
        gross = GROSS * (1.0 - STRESS_CUT * self._stress_c)

        # -------------------------------------------------- off-cycle triggers
        breaks = []
        weak_c, weak_slack = None, None
        for c, p in positions.items():
            r = view.get(c)
            if r is None:
                continue
            px = r.get("Close")
            s100 = r.get("sma100")
            if not ok(px) or not ok(s100) or s100 <= 0:
                continue
            slack = px / s100 - 1.0
            if weak_slack is None or slack < weak_slack:
                weak_c, weak_slack = c, slack
            if slack < -BREAK_SMA100 and day - self._break_sold.get(c, -99) > 5:
                breaks.append(c)
        # The ledger demotes, but it never puts me in the market off-schedule: a
        # bookkeeping entry about somebody else's fills is not a reason to pay a
        # spread today. Names I hold that the field is bleeding in, for the journal:
        taxed = [c for c in positions if self._tuition(c) > 0.5]

        off_cycle = bool(breaks) and (day - self._last_offcycle) >= 4
        rebalance = new_month or off_cycle or (day == 0)

        orders = []
        picks, dropped, added = [], [], []
        if rebalance:
            scored = self._rank_universe(view, w_peer, day)
            per_sector = {}
            for sc, c in scored:
                if len(picks) >= MAX_POS:
                    break
                s = sectors.get(c, "Other")
                if per_sector.get(s, 0) >= SECTOR_CAP:
                    continue
                picks.append((c, sc))
                per_sector[s] = per_sector.get(s, 0) + 1

            target = {}
            if picks:
                each = gross / len(picks)
                for c, _ in picks:
                    target[c] = min(each, MAX_W)
                for _ in range(3):
                    short = gross - sum(target.values())
                    if short <= 0.002:
                        break
                    room = [c for c in target if target[c] < MAX_W - 1e-9]
                    if not room:
                        break
                    bump = short / len(room)
                    for c in room:
                        target[c] = min(MAX_W, target[c] + bump)

            floor = max(BAND * equity, MIN_ORDER)
            sells, buys, proceeds = [], [], 0.0
            for c, p in positions.items():
                val = p.get("value", 0.0)
                val = float(val) if ok(val) else 0.0
                cw = p.get("weight", 0.0)
                cw = float(cw) if ok(cw) else 0.0
                tw = target.get(c, 0.0)
                if tw <= 0.0:
                    if val < EXIT_DUST:
                        continue
                    why = ("broke 8% under its 100d average" if c in breaks else
                           "demoted: the field is bleeding in it" if c in taxed else
                           "fell out of the monthly ranking")
                    sells.append({"code": c, "side": "sell", "all": True, "reason": why})
                    proceeds += val
                    dropped.append(c)
                    if c in breaks:
                        self._break_sold[c] = day
                    continue
                cut = (cw - tw) * equity
                if cut > floor and val > 0:
                    frac = max(0.05, min(0.95, cut / val))
                    sells.append({"code": c, "side": "sell", "fraction": round(frac, 4),
                                  "reason": f"trimming to target {tw:.0%}"})
                    proceeds += val * frac
            want = []
            for c, tw in target.items():
                cw = positions.get(c, {}).get("weight", 0.0)
                cw = float(cw) if ok(cw) else 0.0
                add = (tw - cw) * equity
                if add > floor:
                    want.append((add, c))
            want.sort(key=lambda t: (-t[0], t[1]))
            budget = cash + 0.998 * proceeds - CASH_BUFFER * equity
            tot_want = sum(a for a, _ in want)
            k = min(1.0, budget / tot_want) if tot_want > 0 else 0.0
            for add, c in want:
                sar = add * k
                if sar < MIN_ORDER:
                    continue
                src = self._source.get(c) if w_peer > 0 else None
                if src and self._conv.get(c, 0.0) >= 0.05:
                    why = f"rank + {src}'s book"
                else:
                    why = "top of my own ranking"
                buys.append({"code": c, "side": "buy", "sar": round(sar, 2),
                             "reason": why})
                if c not in positions:
                    added.append(c)
            orders = sells + buys
            if orders:
                self._rebals += 1
                if off_cycle and not new_month:
                    self._last_offcycle = day
            self._own_picks = sum(1 for c, _ in picks if self._conv.get(c, 0.0) < 0.02)

        # --------------------------------------------------------- the reading
        sentiment = 0.9 * (breadth - 0.5) + 6.0 * tret + 2.0 * my_r21
        if panel:
            sentiment = 0.75 * sentiment + 0.25 * max(-1.0, min(1.0, 6.0 * panel_r21))
        sentiment = max(-1.0, min(1.0, sentiment))

        if rebalance and not picks:
            mood = "risk off"
        elif self._stress_c > 0.30:
            mood = "flinching with the field"
        elif breaks:
            mood = "cutting a break"
        elif my_dd < -0.10:
            mood = "underwater, holding process"
        elif w_peer >= 0.25:
            mood = "following the leader"
        elif panel and my_r63 > lead_r63:
            mood = "out in front"
        elif sentiment > 0.35:
            mood = "constructive"
        else:
            mood = MOODS_OK[day % len(MOODS_OK)]

        note = self._write(day, rebalance, new_month, picks, added, dropped,
                           breaks, taxed, names, sectors, positions, equity, cash,
                           invested, my_dd, my_r63, panel, lead_h, lead_r63,
                           lead_r21, panel_r21, w_peer, field_cash, breadth,
                           tret, rows, weak_c, weak_slack)

        return {"orders": self._clean(orders), "sentiment": round(sentiment, 3),
                "mood": mood, "note": note}

    @staticmethod
    def _clean(orders):
        out = []
        for o in orders:
            good = bool(o.get("code")) and o.get("side") in ("buy", "sell")
            for key in ("sar", "shares", "fraction", "weight"):
                v = o.get(key)
                if v is None:
                    continue
                if not ok(v) or v <= 0:
                    good = False
            if good:
                out.append(o)
        return out

    # ------------------------------------------------------------- the journal
    def _write(self, day, rebalance, new_month, picks, added, dropped, breaks,
               taxed, names, sectors, positions, equity, cash, invested, my_dd,
               my_r63, panel, lead_h, lead_r63, lead_r21, panel_r21, w_peer,
               field_cash, breadth, tret, rows, weak_c, weak_slack):
        def nm(c):
            n = names.get(c, c)
            return f"{n} ({c})" if n != c else str(c)

        def lst(codes, k=3):
            head = ", ".join(nm(c) for c in codes[:k])
            more = len(codes) - k
            return f"{head} (+{more} more)" if more > 0 else head

        lead = lead_h or "nobody"

        if rebalance and picks:
            top_c, top_s = picks[0]
            book = lst([c for c, _ in picks[1:]], 3)
            if new_month:
                head = f"Turn of the month, re-rank #{self._rebals}."
            elif breaks:
                head = f"{nm(breaks[0])} broke its 100-day; forced re-rank."
            else:
                head = f"Off-cycle re-rank #{self._rebals}."
            tail = []
            if added:
                tail.append(f"in: {lst(added)}")
            if dropped:
                tail.append(f"out: {lst(dropped)}")
            mid = "; ".join(tail) if tail else "no changes cleared the 4% band"
            if w_peer > 0.05 and lead_h:
                extra = (f" Follow dial at {w_peer:.2f} — {lead} is {lead_r63:+.1%} "
                         f"over 63 sessions against my {my_r63:+.1%}, so his book gets "
                         f"a vote on my ranking. It does not get a veto over my screens.")
            elif panel:
                extra = (f" Follow dial at zero: I am {my_r63:+.1%} over 63 sessions "
                         f"against {lead} at {lead_r63:+.1%}. Nobody out there is worth "
                         f"copying today, so this book is entirely mine.")
            else:
                extra = (f" No rival books on the tape — this is the momentum engine "
                         f"running solo, {self._own_picks} of {len(picks)} names found "
                         f"by nothing but the ranking.")
            board = f", then {book}" if book else ""
            return (f"{head} Top of the board: {nm(top_c)} at score {top_s:+.2f}"
                    f"{board}. {mid}. Book is {len(picks)} names at roughly "
                    f"{(GROSS / max(1, len(picks))):.0%} each, cash "
                    f"{cash:,.0f} SAR.{extra}")

        if rebalance and not picks:
            return (f"Nothing clears the screens today — no name in this market is "
                    f"above both its 50- and 100-day average with SAR 5m of daily "
                    f"traded value behind it. Breadth {breadth:.0%}. Going to cash and "
                    f"waiting; an empty ranking is a position, and it is the one that "
                    f"kept me out of the worst of this tape. Equity {equity:,.0f} SAR.")

        # quiet days — rotate through what is actually worth recording
        lines = []
        big_c, big_w = None, 0.0
        for c, p in positions.items():
            w = p.get("weight", 0.0)
            if ok(w) and w > big_w:
                big_c, big_w = c, float(w)
        if big_c:
            up = positions[big_c].get("unrealized_pct", 0.0)
            up = float(up) if ok(up) else 0.0
            src = self._source.get(big_c)
            tag = (f" — {src} was in it before me" if src and w_peer > 0.05
                   else " — my own find")
            lines.append(f"Largest line is {nm(big_c)} at {big_w:.0%} of the book, "
                         f"{up:+.1%} on cost{tag}. Nothing to do: the monthly re-rank "
                         f"is the only thing allowed to sell a winner in this system.")
        if panel:
            worst = rows[-1]
            lines.append(f"Scorecard: {lead} leads the field at {lead_r63:+.1%} over "
                         f"63 sessions ({lead_r21:+.1%} over 21); {worst[1]} brings up "
                         f"the rear at {worst[2]:+.1%}. I sit at {my_r63:+.1%}. "
                         f"Follow dial {w_peer:.2f}.")
            lines.append(f"Panel blended 21-day {panel_r21:+.1%}, field cash "
                         f"{field_cash:.0%}. My gross is {invested:.0%} with "
                         f"{cash:,.0f} SAR resting. When eight books flinch at once "
                         f"that is data; when one does it is a mood.")
        else:
            lines.append(f"No rival books on the tape, so the meta layer is idle and "
                         f"the momentum engine carries it alone: {len(positions)} "
                         f"names, {invested:.0%} invested, {cash:,.0f} SAR in reserve. "
                         f"Breadth {breadth:.0%}, TASI {tret:+.2%}.")
            lines.append(f"Nobody to grade tonight — the scorecard is a blank page and "
                         f"the ranking is the only opinion in this book. That is fine. "
                         f"The follow dial was always meant to be an accelerator, not "
                         f"an engine. {my_r63:+.1%} over 63 sessions, {my_dd:+.1%} off "
                         f"my high, {invested:.0%} invested.")
            lines.append(f"Solo again. Equity {equity:,.0f} SAR across "
                         f"{len(positions)} lines, breadth {breadth:.0%}. I would "
                         f"rather have rivals to read — a field is free research and "
                         f"free warnings — but a ranking that only works when somebody "
                         f"else is right is not a strategy, it is a subscription.")
        if weak_c is not None and weak_slack is not None:
            if weak_slack < 0:
                lines.append(f"Closest thing to a problem: {nm(weak_c)} is "
                             f"{weak_slack:+.1%} against its 100-day. The break rule "
                             f"fires at {-BREAK_SMA100:.0%}, so it has "
                             f"{abs(weak_slack + BREAK_SMA100):.1%} of rope left. I do "
                             f"not pre-empt my own rules; I let them trigger.")
            else:
                lines.append(f"Every line is above its 100-day — the weakest, "
                             f"{nm(weak_c)}, still has {weak_slack:+.1%} of clearance. "
                             f"Nothing to cut, nothing to add until the calendar says "
                             f"so. {invested:.0%} invested, {cash:,.0f} SAR idle.")
        tuition_c, tuition_r, tuition_v = None, 0.0, 0.0
        for c in self._burn:
            f = self._traded.get(c, 0.0)
            b = self._burn.get(c, 0.0)
            if f >= TUIT_FLOOR and b < 0:
                r = b / f
                if r < tuition_r:
                    tuition_c, tuition_r, tuition_v = c, r, b
        if tuition_c and tuition_r < -0.02:
            lines.append(f"Tuition ledger: the field has given back "
                         f"{abs(tuition_v):,.0f} SAR in {nm(tuition_c)}, "
                         f"{abs(tuition_r):.1%} of every riyal it has pushed through "
                         f"the name. Demoted on my borderline list. Somebody paid for "
                         f"that lesson; I intend to attend it for free.")
        if taxed:
            lines.append(f"I am holding {lst(taxed)} while the field bleeds in it. "
                         f"The ledger demotes, it does not veto — it only applies "
                         f"below my own top {MAX_POS}, and that name is above the "
                         f"line on momentum. Other people's fills are evidence about "
                         f"other people at least as much as about the stock.")
        if picks or positions:
            secs = {}
            for c in positions:
                s = sectors.get(c, "Other")
                secs[s] = secs.get(s, 0) + 1
            spread = ", ".join(f"{s} x{n}" for s, n in
                               sorted(secs.items(), key=lambda t: (-t[1], t[0]))[:3])
            if spread:
                lines.append(f"Book by sector: {spread}. Cap is {SECTOR_CAP} names per "
                             f"sector — the ranking would happily put five banks in "
                             f"here and one bad week would take all five out together. "
                             f"{invested:.0%} invested, equity {equity:,.0f} SAR.")
        lines.append(f"Holding pattern. {len(positions)} names, {invested:.0%} "
                     f"invested, {my_dd:+.1%} off my own high, equity "
                     f"{equity:,.0f} SAR. Breadth {breadth:.0%}, TASI {tret:+.2%}. "
                     f"Next scheduled re-rank is the first session of next month — "
                     f"between now and then only a 100-day break gets me to trade.")
        if self._stress_c > 0.15:
            lines.append(f"Field stress reading {self._stress_c:.2f}: the panel is "
                         f"{panel_r21:+.1%} over 21 sessions with {field_cash:.0%} in "
                         f"cash. Gross trimmed toward "
                         f"{GROSS * (1 - STRESS_CUT * self._stress_c):.0%}. I would "
                         f"rather flinch early with the field than explain a drawdown "
                         f"alone.")
        if my_r63 > 0.02 and panel and my_r63 > lead_r63:
            lines.append(f"Ahead of the field: {my_r63:+.1%} over 63 sessions against "
                         f"{lead} at {lead_r63:+.1%}. The follow dial is off and stays "
                         f"off while that holds. Copying is a tool, not an identity — "
                         f"{self._own_picks} of the names I hold came out of my own "
                         f"ranking with no help from anyone's book.")
        return lines[day % len(lines)]


STRATEGY = Malik()
