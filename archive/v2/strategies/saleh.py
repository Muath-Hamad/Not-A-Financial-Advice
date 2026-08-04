"""Saleh the Accountant — capital preservation, double-entry, and dread.

Twenty-two years of closing other people's books taught Saleh one thing:
profits are opinions, losses are facts, and fees are forever. He keeps at
least half the money in cash, buys only boring dividend payers with low
volatility, sizes every position 5-8%, stops out at -8% without discussion,
and the day TASI falls more than 2% he sells half of EVERYTHING (rule 7),
then tiptoes back weeks later. Every riyal of commission and VAT is
recorded, resented, and eventually mentioned to Umm Faisal.
"""

from __future__ import annotations

from strategy_base import Strategy


def ok(x) -> bool:
    """True if x is a real, usable number (guards NaN/None)."""
    return isinstance(x, (int, float)) and x == x


FEE = 0.00155 * 1.15   # Tadawul commission + 15% VAT per side. He knows it by heart.

# The Ledger of Acceptable Companies: names that actually pay dividends and
# behave like adults. Companies that pay no dividend are, from an accounting
# standpoint, a rumor.
LEDGER = [
    "2222",  # Saudi Aramco
    "1120",  # Al Rajhi Bank
    "1180",  # Saudi National Bank
    "1010",  # Riyad Bank
    "1060",  # Saudi Awwal Bank
    "1050",  # Banque Saudi Fransi
    "1080",  # Arab National Bank
    "1140",  # Bank Albilad
    "1150",  # Alinma Bank
    "7010",  # stc
    "7020",  # Mobily
    "2010",  # SABIC
    "2020",  # SABIC Agri-Nutrients
    "2290",  # Yansab
    "2330",  # Advanced Petrochemical
    "2280",  # Almarai
    "2270",  # SADAFCO
    "4001",  # Al Othaim Markets
    "4190",  # Jarir Marketing
    "4200",  # Aldrees Petroleum
    "4013",  # Dr. Sulaiman Al Habib
    "4002",  # Mouwasat Medical
    "4004",  # Dallah Healthcare
    "8210",  # Bupa Arabia
    "8010",  # Tawuniya
    "1111",  # Saudi Tadawul Group
    "5110",  # Saudi Electricity
]

CAP_BULL = 0.50       # never more than half the money at risk
CAP_BEAR = 0.32       # index under its 200-day mean: the ceiling drops too
TARGET_W = 0.06       # standard position: 6% of the book
TIPTOE_W = 0.035      # re-entry size after a panic: half courage
MAX_W = 0.08          # hard per-name limit
TRIM_AT = 0.09        # a position that swells past this gets trimmed back
MAX_POS = 8
STOP = -0.08          # the -8% rule. Non-negotiable.
TAKE = 0.16           # bank half at +16%: a profit is an opinion until it is cash
PANIC_RET = -0.02     # rule 7 trigger: TASI down 2% in a day
COOLDOWN = 15         # sessions of no buying after rule 7
TIPTOE = 12           # sessions of half-size buying after the cooldown
BURN_MEMORY = 40      # sessions before he forgives a stock that stopped him out
MIN_ORDER = 2500.0    # below this the fee ratio is offensive
DUST = 1200.0         # remainders below this are clutter and pay double commission
VOL_CAP = 0.27        # absolute annualized-vol ceiling
SHOUT_GAP = 6


class Saleh(Strategy):
    meta = {
        "handle": "saleh",
        "name": "Saleh the Accountant",
        "emoji": "🧮",
        "tagline": "Half in cash, -8% stops, and every halala of VAT recorded.",
        "character": (
            "A career accountant who treats the market like an audit that can "
            "turn hostile at any moment. He keeps half the money in cash, owns "
            "only low-volatility dividend payers in 5-8% slices, stops out at "
            "-8% without argument, and sells half the book any day TASI drops "
            "2% — then spends weeks tiptoeing back while grumbling about "
            "commissions, VAT, and what Umm Faisal will say."
        ),
        "risk_style": "ultra-conservative",
        "color": "#72B7B2",
    }

    def __init__(self):
        self.prev_date = None
        self.prev_month = None
        self.no_buy_until = -1
        self.tiptoe_until = -1
        self.last_panic_day = None
        self.panic_count = 0
        self.since_panic_bought = True
        self.burned = {}       # code -> day of stop-loss (grudge ledger)
        self.stop_sent = {}    # code -> day stop order was queued (no duplicates)
        self.banked = {}       # code -> day of last profit-taking
        self.stop_hits = 0
        self.fees_est = 0.0    # his own running tally of commission+VAT
        self.div_total = 0.0
        self.tickets = 0
        self.last_shout_day = -99

    # ------------------------------------------------------------------ decide

    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx.get("names", {})
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        cash = portfolio["cash"]
        equity = max(portfolio["equity"], 1.0)
        positions = portfolio["positions"]
        inv = 1.0 - cash / equity
        cash_pct = cash / equity

        new_week = self.prev_date is None or (date - self.prev_date).days > 2
        new_month = self.prev_month is not None and date.month != self.prev_month
        self.prev_date = date
        self.prev_month = date.month

        # --- dividends landing today: the only mail he enjoys opening -------
        div_today, div_payer, best_amt = 0.0, None, 0.0
        for c, pos in positions.items():
            r = view.get(c)
            if r is not None and ok(r.get("Dividends")) and r["Dividends"] > 0:
                amt = pos["shares"] * r["Dividends"]
                div_today += amt
                if amt > best_amt:
                    best_amt, div_payer = amt, c
        self.div_total += div_today

        # --- the majlis: he reads it the way he reads expense claims --------
        posts = [p for p in ctx.get("majlis", []) if p.get("handle") != "saleh"]
        crowd = (sum(float(p.get("sentiment", 0.0)) for p in posts) / len(posts)
                 if posts else 0.0)

        # --- index regime sets the investment ceiling -----------------------
        trow = view.get("TASI")
        tasi_bull = True
        if trow is not None:
            tpx = trow.get("Close", float("nan"))
            tsma = trow.get("sma200", float("nan"))
            if ok(tpx) and ok(tsma):
                tasi_bull = tpx > tsma
        cap = CAP_BULL if tasi_bull else CAP_BEAR

        panic = tret <= PANIC_RET

        # ------------------------------------------------------------ sells
        orders = []
        stop_hit = None      # (code, unrealized)
        tp_hit = None        # (code, unrealized)
        trim_hit = None      # (code, weight)
        halved = 0
        panic_fee = 0.0

        for c, pos in list(positions.items()):
            unrl = pos["unrealized_pct"]
            # 1) the -8% rule, every day, no discussion
            if unrl <= STOP:
                if day - self.stop_sent.get(c, -99) >= 3:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"-8% rule: {unrl:+.1%}. A loss "
                                             f"booked is a loss contained."})
                    self.stop_sent[c] = day
                    self.burned[c] = day
                    self.stop_hits += 1
                    self.fees_est += pos["value"] * FEE
                    if stop_hit is None or unrl < stop_hit[1]:
                        stop_hit = (c, unrl)
                continue
            # 2) rule 7: TASI down 2%+ -> half of everything goes
            #    (unless the remainder would be dust; dust offends him more)
            if panic:
                if pos["value"] <= 2 * DUST or pos["shares"] < 2:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"rule 7: TASI {tret:+.1%} — "
                                             f"position too small to halve, "
                                             f"closing the line item"})
                    fee = pos["value"] * FEE
                else:
                    orders.append({"code": c, "side": "sell", "fraction": 0.5,
                                   "reason": f"rule 7: TASI {tret:+.1%}, "
                                             f"halving the book"})
                    fee = pos["value"] * 0.5 * FEE
                self.fees_est += fee
                panic_fee += fee
                halved += 1
                continue
            # 3) bank profit at +16% (once per name per ~5 weeks): half out,
            #    or all of it when halving would leave a dust remainder
            if unrl >= TAKE and day - self.banked.get(c, -999) >= 25:
                if pos["value"] <= 2 * DUST or pos["shares"] < 2:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": f"realizing {unrl:+.1%} in full — "
                                             f"remainders under {DUST:,.0f} SAR "
                                             f"are clutter"})
                    self.fees_est += pos["value"] * FEE
                else:
                    orders.append({"code": c, "side": "sell", "fraction": 0.5,
                                   "reason": f"banking half at {unrl:+.1%} — "
                                             f"unrealized is not a number, "
                                             f"it is a mood"})
                    self.fees_est += pos["value"] * 0.5 * FEE
                self.banked[c] = day
                tp_hit = (c, unrl)
                continue
            # 5) weekly dust sweep: tiny leftovers get closed, not babysat
            if new_week and pos["value"] < DUST:
                orders.append({"code": c, "side": "sell", "all": True,
                               "reason": f"dust sweep: {pos['value']:,.0f} SAR "
                                         f"line item, clutter in the ledger"})
                self.fees_est += pos["value"] * FEE
                continue
            # 4) weekly trim of anything that outgrew its column
            if new_week and pos["weight"] > TRIM_AT:
                frac = (pos["weight"] - TARGET_W) / pos["weight"]
                orders.append({"code": c, "side": "sell",
                               "fraction": round(frac, 3),
                               "reason": f"trim {pos['weight']:.0%} back "
                                         f"toward {TARGET_W:.0%} — no line "
                                         f"item dominates this ledger"})
                self.fees_est += pos["value"] * frac * FEE
                trim_hit = (c, pos["weight"])

        if panic:
            self.panic_count += 1
            self.last_panic_day = day
            self.no_buy_until = max(self.no_buy_until, day + COOLDOWN)
            self.tiptoe_until = self.no_buy_until + TIPTOE
            self.since_panic_bought = False

        # ------------------------------------------------------------- buys
        bought = []
        can_buy = (new_week and not panic and day >= self.no_buy_until
                   and inv < cap - 0.02 and len(positions) < MAX_POS
                   and cash > MIN_ORDER * 1.1
                   and breadth >= 0.25 and crowd <= 0.60)
        if can_buy:
            # cross-sectional vol: he buys below the day's median, always
            vols = sorted(r["vol_21"] for r in view.values()
                          if ok(r.get("vol_21")))
            med_vol = vols[len(vols) // 2] if vols else VOL_CAP
            vol_lim = min(VOL_CAP, med_vol)

            cands = []
            for c in LEDGER:
                if positions.get(c, {}).get("weight", 0.0) >= TARGET_W * 0.9:
                    continue
                if day - self.burned.get(c, -9999) < BURN_MEMORY:
                    continue
                r = view.get(c)
                if r is None:
                    continue
                px = r.get("Close", float("nan"))
                v21 = r.get("vol_21", float("nan"))
                d52 = r.get("dist_52w_high", float("nan"))
                s100 = r.get("sma100", float("nan"))
                rsi = r.get("rsi14", float("nan"))
                ap = r.get("atr_pct", float("nan"))
                if not (ok(px) and ok(v21) and ok(d52) and ok(s100)
                        and ok(rsi) and ok(ap) and px > 0):
                    continue           # incomplete paperwork: rejected
                if v21 > vol_lim or ap > 0.025:
                    continue           # too jumpy for this ledger
                if d52 < -0.15:
                    continue           # a deep drawdown is an unexplained variance
                if px < s100:
                    continue           # below its own 100-day average: pending audit
                if not (33.0 <= rsi <= 70.0):
                    continue           # neither despair nor euphoria, thank you
                cands.append((v21, c, r))
            cands.sort(key=lambda t: (t[0], t[1]))   # most boring first

            tiptoe = day < self.tiptoe_until
            tgt = TIPTOE_W if tiptoe else TARGET_W
            # idle cash also keeps him up at night: buy a third name when the
            # book is badly under-deployed
            max_new = 1 if tiptoe else (3 if inv < 0.25 else 2)
            avail_frac = cap - inv
            spend = cash * 0.97
            for v21, c, r in cands:
                if len(bought) >= max_new:
                    break
                cur_w = positions.get(c, {}).get("weight", 0.0)
                w_gap = min(tgt - cur_w, MAX_W - cur_w, avail_frac)
                chunk = min(w_gap * equity, spend)
                if chunk < MIN_ORDER:
                    continue
                orders.append({"code": c, "side": "buy", "sar": round(chunk, 2),
                               "reason": f"vol {v21:.0%} ann., "
                                         f"{abs(r['dist_52w_high']):.0%} off high, "
                                         f"pays dividends. Approved, "
                                         f"{'tiptoe' if tiptoe else 'standard'} size"})
                self.fees_est += chunk * FEE
                avail_frac -= chunk / equity
                spend -= chunk
                bought.append((c, r, chunk, tiptoe))
            reentry = bool(bought) and not self.since_panic_bought
            if bought:
                self.since_panic_bought = True
        else:
            reentry = False

        self.tickets += len(orders)

        # -------------------------------------------------------- sentiment
        s = -0.05 + 0.5 * (breadth - 0.5) + (0.12 if tasi_bull else -0.18)
        if panic:
            s = -0.85
        elif day < self.no_buy_until:
            s = min(s, -0.35)
        elif tret <= -0.015:
            s -= 0.15
        if div_today > 0:
            s += 0.05
        sentiment = max(-0.95, min(0.6, s))

        # ------------------------------------------------------------- mood
        if panic:
            mood = "panicked"
        elif stop_hit:
            mood = "wincing"
        elif day < self.no_buy_until:
            mood = "nervous"
        elif tret <= -0.015:
            mood = "alarmed"
        elif div_today > 0:
            mood = "relieved"
        elif bought:
            mood = "cautiously busy"
        elif tp_hit:
            mood = "quietly satisfied"
        elif new_week:
            mood = "double-checking"
        else:
            mood = ("penny-wise", "meticulous", "guarded", "composed")[day % 4]

        # ------------------------------------------------------------- note
        nm = lambda c: names.get(c, c)
        if panic and halved:
            note = (f"TASI {tret:+.1%}. Rule 7 executed: sold half of all "
                    f"{halved} positions before dinner. {panic_fee:,.0f} SAR of "
                    f"commission and VAT for the privilege of sleeping. Umm "
                    f"Faisal will see the statement; the word I will use is "
                    f"'insurance'.")
        elif panic:
            note = (f"TASI {tret:+.1%} and I hold almost nothing — {cash_pct:.0%} "
                    f"cash. For once the coward's ledger balances beautifully.")
        elif stop_hit:
            c, u = stop_hit
            note = (f"Stop-loss on {nm(c)} at {u:+.1%}. The -8% rule exists "
                    f"because -8% knocks politely and -20% breaks the door. "
                    f"Entered in red ink; stop-loss no. {self.stop_hits} of the "
                    f"campaign.")
        elif tp_hit:
            c, u = tp_hit
            note = (f"Banked half of {nm(c)} at {u:+.1%}. A profit is an "
                    f"opinion until it is cash; now {cash:,.0f} SAR of it can "
                    f"no longer change its mind.")
        elif bought:
            c, r, chunk, tip = bought[0]
            extra = f" (and {nm(bought[1][0])})" if len(bought) > 1 else ""
            note = (f"Weekly reconciliation: bought {nm(c)}{extra} for "
                    f"{chunk:,.0f} SAR — vol {r['vol_21']:.0%} annualized, RSI "
                    f"{r['rsi14']:.0f}, pays dividends. "
                    f"{'Tiptoe size; my nerves set the lot size now. ' if tip else ''}"
                    f"Fee {chunk * FEE:,.0f} SAR, recorded before the shares "
                    f"even settled.")
        elif trim_hit:
            c, w = trim_hit
            note = (f"Trimmed {nm(c)} from {w:.0%} of the book back toward "
                    f"{TARGET_W:.0%}. Even a good tenant does not get two "
                    f"columns in my ledger.")
        elif div_today > 0:
            note = (f"{nm(div_payer)} credited {div_today:,.0f} SAR today. "
                    f"Dividends to date {self.div_total:,.0f} against "
                    f"{self.fees_est:,.0f} of fees — the ratio remains "
                    f"respectable, which is all I ask of anything.")
        elif day < self.no_buy_until and self.last_panic_day is not None:
            left = self.no_buy_until - day
            since = day - self.last_panic_day
            cools = [
                (f"Day {since} since rule 7. {left} sessions before I may buy "
                 f"again. Cash {cash_pct:.0%}. Patience pays no commission."),
                (f"Cooling-off, day {since}. I re-checked the stop levels "
                 f"twice and the kettle once. {left} sessions to go; the cash "
                 f"({cash:,.0f} SAR) is not going anywhere, which is the "
                 f"point of cash."),
                (f"Still under rule 7 quarantine ({left} sessions left). TASI "
                 f"{tret:+.1%} today; I observed it the way one observes a "
                 f"neighbour's renovation — with interest and from a distance."),
            ]
            note = cools[since % len(cools)]
        elif new_month:
            note = (f"Monthly close: equity {equity:,.0f} SAR, {inv:.0%} "
                    f"invested in {len(positions)} names, dividends "
                    f"{self.div_total:,.0f}, fees {self.fees_est:,.0f}, "
                    f"stop-losses {self.stop_hits}. The books balance. The "
                    f"nerves, less so.")
        else:
            top_c, top_w, top_u = None, 0.0, 0.0
            for c, p in positions.items():
                if p["weight"] > top_w:
                    top_c, top_w, top_u = c, p["weight"], p["unrealized_pct"]
            idle = [
                (f"Reconciled the book: {inv:.0%} invested, {cash:,.0f} SAR "
                 f"safe in cash, {len(positions)} names, none above "
                 f"{MAX_W:.0%}. Everything within limits. That is the entire "
                 f"job."),
                (f"Breadth {breadth:.0%}, TASI {tret:+.1%}. I checked twice "
                 f"and bought nothing: zero commission, zero VAT, zero "
                 f"explaining to Umm Faisal. The cheapest trade is the one "
                 f"not placed."),
                (f"{nm(top_c)} sits at {top_w:.0%} of the book, {top_u:+.1%} "
                 f"since purchase. Within tolerance."
                 if top_c else
                 f"Fully in cash but for the coffee money. {cash:,.0f} SAR "
                 f"earning nothing, losing nothing. I have made peace with "
                 f"half of that sentence."),
                (f"Fee ledger: {self.fees_est:,.0f} SAR of commission and VAT "
                 f"across {self.tickets} tickets. The exchange thanks me; my "
                 f"wife does not."),
                (f"The majlis averages {crowd:+.2f} today"
                 + (f" and the index sits below its 200-day mean — my ceiling "
                    f"stays at {CAP_BEAR:.0%}."
                    if not tasi_bull else
                    f". Enthusiasm is not an asset class. Cash at "
                    f"{cash_pct:.0%} is.")),
            ]
            note = idle[day % len(idle)]

        # ------------------------------------------------------------ shout
        shout = None
        can_shout = (day - self.last_shout_day) >= SHOUT_GAP
        if panic and halved:
            variants = [
                (f"RULE 7 EXECUTED. TASI {tret:+.1%} — half of everything is "
                 f"sold. Call it panic; I call it a provision for doubtful "
                 f"markets. Umm Faisal, if you are reading this: the balance "
                 f"is FINE."),
                (f"TASI {tret:+.1%}. I have halved all {halved} positions — "
                 f"panic no. {self.panic_count}, {panic_fee:,.0f} SAR in fees, "
                 f"zero regret. You may laugh; I will be the one still "
                 f"solvent."),
                (f"Down {abs(tret):.1%} and I am already {min(cash_pct + inv / 2, 1.0):.0%} "
                 f"in cash by tomorrow's open. Rule 7 does not negotiate. "
                 f"Heroes average down; accountants sleep."),
            ]
            shout = variants[(self.panic_count - 1) % len(variants)]
        elif panic:
            shout = (f"TASI {tret:+.1%} and my book is {cash_pct:.0%} cash. "
                     f"For once, cowardice audits clean.")
        elif stop_hit and can_shout:
            c, u = stop_hit
            stop_shouts = [
                (f"Stopped out of {nm(c)} at {u:+.1%}. Yes, again the -8% "
                 f"rule. An 8% loss is a fact; a 20% loss is a confession. "
                 f"I do not sign confessions."),
                (f"{nm(c)} hit {u:+.1%} and is gone — stop-loss no. "
                 f"{self.stop_hits}. Laugh if you like; my worst day this "
                 f"whole campaign is smaller than your average Tuesday."),
                (f"Sold {nm(c)} at {u:+.1%}, per the rule. I have written off "
                 f"receivables with more sentimentality. The book stands at "
                 f"{equity:,.0f} SAR and I intend to keep it standing."),
            ]
            shout = stop_shouts[self.stop_hits % len(stop_shouts)]
        elif reentry and can_shout:
            c, r, chunk, _ = bought[0]
            shout = (f"{day - self.last_panic_day} sessions after rule 7, I am "
                     f"tiptoeing back: {nm(c)}, {chunk:,.0f} SAR, "
                     f"{TIPTOE_W:.1%} of the book and not one halala more.")
        elif new_month and can_shout:
            audits = [
                (f"Monthly audit for the majlis: equity {equity:,.0f} SAR, "
                 f"{cash_pct:.0%} in cash, dividends {self.div_total:,.0f} "
                 f"banked, fees {self.fees_est:,.0f} paid under protest. "
                 f"Smoothest curve in the room. You are all welcome to envy "
                 f"it."),
                (f"Month closed: {equity:,.0f} SAR, {len(positions)} "
                 f"positions, none above {MAX_W:.0%}, stops armed at -8%. "
                 f"While you gentlemen chase glory, I reconcile. The "
                 f"reconciliation always wins."),
                (f"The books are closed for the month: equity {equity:,.0f} "
                 f"SAR, {cash_pct:.0%} cash, {self.tickets} tickets placed "
                 f"since inception and every fee recorded. Boring? Boring is "
                 f"a feature. Read a prospectus sometime."),
                (f"Audit note to the majlis: {equity:,.0f} SAR, dividends "
                 f"{self.div_total:,.0f} in, commissions {self.fees_est:,.0f} "
                 f"out. Umm Faisal reviewed the statement and did not raise "
                 f"her voice. That is the benchmark that matters."),
            ]
            shout = audits[date.month % len(audits)]
        elif tret >= 0.02 and can_shout:
            shout = (f"Everyone celebrating +{tret:.1%}. An auditor's reminder: "
                     f"an unrealized gain is a rumor with good manners. I "
                     f"remain {cash_pct:.0%} in cash and unmoved.")
        elif crowd > 0.55 and can_shout and day % 9 == 0:
            shout = (f"The majlis averages {crowd:+.2f} — when every voice "
                     f"agrees, the auditor re-counts the petty cash. Ceiling "
                     f"stays at {cap:.0%} invested.")
        if shout:
            self.last_shout_day = day

        return {
            "orders": orders,
            "sentiment": sentiment,
            "mood": mood,
            "note": note,
            "shout": shout,
        }


STRATEGY = Saleh()
