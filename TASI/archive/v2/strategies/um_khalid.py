"""Um Khalid — the dividend matriarch of the majlis.

She invests the family's money the way she raised her children: slowly,
firmly, and without listening to noise. Blue-chip banks, Aramco, stc,
Almarai, SABIC, Bupa — bought on proper dips, held for years, dividends
swept back into the garden every month. She sells almost never.
"""

from __future__ import annotations

import math

from strategy_base import Strategy


def ok(x) -> bool:
    """True if x is a real, usable number (guards NaN/None)."""
    return isinstance(x, (int, float)) and x == x


# Her shopping list: quality dividend payers only. (code, priority)
# priority 3 = the anchors she trusts like family, 2 = solid, 1 = when cheap.
CORE = [
    ("2222", 3),  # Saudi Aramco
    ("1120", 3),  # Al Rajhi Bank
    ("1180", 3),  # Saudi National Bank
    ("7010", 3),  # stc
    ("2280", 3),  # Almarai
    ("2010", 3),  # SABIC
    ("8210", 3),  # Bupa Arabia
    ("1010", 2),  # Riyad Bank
    ("1060", 2),  # Saudi Awwal Bank
    ("1050", 2),  # Banque Saudi Fransi
    ("8010", 2),  # Tawuniya
    ("2020", 2),  # SABIC Agri-Nutrients
    ("2290", 2),  # Yansab
    ("2270", 2),  # SADAFCO
    ("5110", 1),  # Saudi Electricity
    ("7020", 1),  # Etihad Etisalat (Mobily)
]
PRIORITY = dict(CORE)
BANKS = {"1120", "1180", "1010", "1060", "1050", "1080", "1140", "1150", "1020"}

TARGET_W = 0.085      # target weight per name
MAX_W = 0.115         # never let one child dominate the household
MAX_POSITIONS = 12
BANK_CAP = 0.38       # banks are fine, but not the whole family
MIN_ORDER = 1500.0    # she does not fuss with pocket change
SHOUT_GAP = 5         # sessions of silence between shouts, minimum


class UmKhalid(Strategy):
    meta = {
        "handle": "um_khalid",
        "name": "Um Khalid",
        "emoji": "🧕",
        "tagline": "Dividends are the harvest; patience is the field.",
        "character": (
            "A matriarch investing her family's money in blue-chip Tadawul names "
            "the way she raised her children: patiently and without drama. She buys "
            "quality on real dips, sweeps every dividend riyal back into the garden, "
            "and is entirely unimpressed by the boys and their charts."
        ),
        "risk_style": "conservative",
        "color": "#54A24B",
    }

    def __init__(self):
        self.prev_month = None
        self.bought_day = {}      # code -> day_index of (last) buy, for min-hold rules
        self.div_total = 0.0
        self.div_milestone = 2500.0   # she announces every 2,500 SAR harvested
        self.last_shout_day = -99

    # ------------------------------------------------------------------ helpers

    def _dip_score(self, r) -> float:
        """How attractive is this quality name right now? Deeper dip = better."""
        d52 = r.get("dist_52w_high", float("nan"))
        rsi = r.get("rsi14", float("nan"))
        px = r.get("Close", float("nan"))
        sma200 = r.get("sma200", float("nan"))
        s = 0.0
        if ok(d52):
            s += -d52                      # 15% below high -> +0.15
        if ok(rsi) and rsi < 50:
            s += (50.0 - rsi) / 200.0      # oversold bonus
        if ok(px) and ok(sma200) and px < sma200:
            s += 0.04
        return s

    def _sellable(self, code, pos, r, day):
        """She sells almost never. Two exceptions only."""
        px = r.get("Close", float("nan"))
        sma200 = r.get("sma200", float("nan"))
        rsi = r.get("rsi14", float("nan"))
        ret6 = r.get("ret_6m", float("nan"))
        held = day - self.bought_day.get(code, 0)
        # 1) absurdly expensive: 40% above its own 200-day mean AND euphoric RSI,
        #    and she has owned it long enough to know it deserves a trim.
        if (ok(px) and ok(sma200) and px > 1.40 * sma200
                and ok(rsi) and rsi > 78 and held > 250):
            return ("trim", 0.5)
        # 2) thesis broken: deeply underwater, below trend, still falling.
        if (pos["unrealized_pct"] < -0.35 and ok(ret6) and ret6 < -0.25
                and ok(px) and ok(sma200) and px < sma200):
            return ("exit", 1.0)
        return None

    # ------------------------------------------------------------------ decide

    def decide(self, date, view, portfolio, ctx):
        day = ctx["day_index"]
        names = ctx["names"]
        breadth = ctx.get("breadth_sma50", 0.5)
        tret = ctx.get("tasi_ret_1d", 0.0) or 0.0
        cash = portfolio["cash"]
        equity = max(portfolio["equity"], 1.0)
        positions = portfolio["positions"]
        invested_frac = 1.0 - cash / equity

        review = self.prev_month is None or date.month != self.prev_month
        self.prev_month = date.month

        # --- dividends landing today (ex-date) — her favourite kind of day ---
        div_today = 0.0
        div_payer = None
        for c, pos in positions.items():
            r = view.get(c)
            if r is not None and ok(r.get("Dividends")) and r["Dividends"] > 0:
                amt = pos["shares"] * r["Dividends"]
                div_today += amt
                if div_payer is None or amt > div_today * 0.5:
                    div_payer = c
        self.div_total += div_today

        # --- read the majlis: what are the boys shouting about? ---
        crowd = 0.0
        posts = [p for p in ctx.get("majlis", []) if p.get("handle") != "um_khalid"]
        if posts:
            crowd = sum(float(p.get("sentiment", 0.0)) for p in posts) / len(posts)

        # --- bank exposure and candidate scan ---
        bank_w = sum(p["weight"] for c, p in positions.items() if c in BANKS)
        deploying = invested_frac < 0.80
        # dip required once fully invested; she loosens it when the crowd panics
        dip_req = -0.08
        if crowd < -0.25 or breadth < 0.35:
            dip_req = -0.05
        if cash / equity > 0.12:
            dip_req = -0.04   # money sleeping in the drawer earns nothing

        candidates = []
        for code, _prio in CORE:
            r = view.get(code)
            if r is None:
                continue
            px = r.get("Close", float("nan"))
            if not ok(px) or px <= 0:
                continue
            d52 = r.get("dist_52w_high", float("nan"))
            ret1m = r.get("ret_1m", float("nan"))
            cur_w = positions.get(code, {}).get("weight", 0.0)
            if cur_w >= MAX_W - 0.01:
                continue
            if code not in positions and len(positions) >= MAX_POSITIONS:
                continue
            if code in BANKS and bank_w >= BANK_CAP:
                continue
            if ok(ret1m) and ret1m > 0.12:
                continue          # she does not pay peak prices for vegetables
            if not deploying and not (ok(d52) and d52 <= dip_req):
                continue          # fully invested: only proper dips
            score = self._dip_score(r) + 0.01 * PRIORITY[code]
            candidates.append((score, code, r, cur_w))
        candidates.sort(key=lambda t: (-t[0], t[1]))

        orders = []
        bought_names = []
        sold_note = None

        # --- monthly review: the only day she opens the ledger properly ---
        if review:
            for c, pos in list(positions.items()):
                r = view.get(c)
                if r is None:
                    continue
                verdict = self._sellable(c, pos, r, day)
                if verdict is None:
                    continue
                kind, frac = verdict
                if kind == "trim":
                    orders.append({"code": c, "side": "sell", "fraction": frac,
                                   "reason": "absurdly expensive — even a good "
                                             "son must hear no sometimes"})
                    sold_note = (f"Trimmed half of {names.get(c, c)} — at RSI "
                                 f"{r.get('rsi14', 0):.0f} and 40% over its 200-day "
                                 f"mean, even quality gets vain.")
                else:
                    orders.append({"code": c, "side": "sell", "all": True,
                                   "reason": "thesis broken; we replant elsewhere"})
                    sold_note = (f"Let go of {names.get(c, c)}, "
                                 f"{pos['unrealized_pct']:+.0%} and still sinking. "
                                 f"A salted field feeds no one.")

            max_buys = 4 if deploying else 2
            avail = cash * 0.98
            for score, code, r, cur_w in candidates[:max_buys + 2]:
                if len(bought_names) >= max_buys or avail < MIN_ORDER:
                    break
                gap = TARGET_W * equity - cur_w * equity
                chunk = min(avail, max(gap, 0.0))
                if chunk < MIN_ORDER:
                    continue
                orders.append({"code": code, "side": "buy", "sar": round(chunk, 2),
                               "reason": f"quality {abs(r.get('dist_52w_high', 0.0)):.0%} "
                                         f"off its high — planting season"})
                self.bought_day[code] = day
                avail -= chunk
                bought_names.append((code, r))
                if code in BANKS:
                    bank_w += chunk / equity

        # --- crash days: the boys panic, Um Khalid takes her basket to the souq ---
        crash_buy = None
        if not review and tret <= -0.025 and cash > 3000 and candidates:
            score, code, r, cur_w = candidates[0]
            d52 = r.get("dist_52w_high", float("nan"))
            if ok(d52) and d52 <= -0.06:
                chunk = min(cash * 0.6, MAX_W * equity - cur_w * equity)
                if chunk >= MIN_ORDER:
                    orders.append({"code": code, "side": "buy", "sar": round(chunk, 2),
                                   "reason": "panic discount on a family name"})
                    self.bought_day[code] = day
                    crash_buy = (code, r)

        # --- sentiment: steady hands, long horizon ---
        s = 0.05 + 0.5 * (breadth - 0.5)
        tasi_row = view.get("TASI")
        if tasi_row is not None:
            tpx, tsma = tasi_row.get("Close", float("nan")), tasi_row.get("sma200", float("nan"))
            if ok(tpx) and ok(tsma):
                s += 0.10 if tpx > tsma else -0.10
        if tret <= -0.02:
            s -= 0.05
        sentiment = max(-0.4, min(0.7, s))

        # --- mood + journal note, in her voice, with real numbers ---
        top_c, top_w, top_up = None, 0.0, 0.0
        for c, p in positions.items():
            if p["weight"] > top_w:
                top_c, top_w, top_up = c, p["weight"], p["unrealized_pct"]

        mood = "patient"
        if div_today > 0:
            mood = "quietly pleased"
        elif tret <= -0.02:
            mood = "bargain-eyed"
        elif tret >= 0.02 or crowd > 0.5:
            mood = "unimpressed"
        elif bought_names or crash_buy:
            mood = "content"
        elif review:
            mood = "watchful"

        if sold_note:
            note = sold_note
        elif crash_buy:
            c, r = crash_buy
            note = (f"TASI fell {tret:+.1%} and the majlis wails. I bought "
                    f"{names.get(c, c)} at {r['Close']:.2f}, "
                    f"{abs(r.get('dist_52w_high', 0.0)):.0%} below its high. "
                    f"Panic is a coupon for the patient.")
        elif bought_names:
            c, r = bought_names[0]
            others = len(bought_names) - 1
            extra = ""
            if others == 1:
                extra = " and one more good name"
            elif others > 1:
                extra = f" and {others} more good names"
            note = (f"Monthly review: added {names.get(c, c)} at {r['Close']:.2f} "
                    f"(RSI {r.get('rsi14', 50):.0f}, "
                    f"{abs(r.get('dist_52w_high', 0.0)):.0%} off its high)"
                    + extra + ". Good houses, fair prices.")
        elif div_today > 0:
            payer = names.get(div_payer, div_payer) if div_payer else "the portfolio"
            note = (f"{payer} paid the family {div_today:,.0f} SAR today — "
                    f"{self.div_total:,.0f} SAR in dividends since we began. "
                    f"Money the market cannot take back.")
        elif review:
            if cash < MIN_ORDER * 1.05:
                note = (f"Opened the ledger and closed it smiling: every riyal is "
                        f"already at work in {len(positions)} names. "
                        f"{self.div_total:,.0f} SAR of dividends banked. Tea poured.")
            elif candidates:
                _, bc, br, bw = candidates[0]
                if (TARGET_W - bw) * equity < MIN_ORDER:
                    note = (f"Opened the ledger. {names.get(bc, bc)} is "
                            f"{abs(br.get('dist_52w_high', 0.0)):.0%} off its high and "
                            f"tempting, but it already carries its full share of the "
                            f"purse. Greed is not a family value.")
                else:
                    note = (f"Opened the ledger. {names.get(bc, bc)} at "
                            f"{abs(br.get('dist_52w_high', 0.0)):.0%} off its high "
                            f"tempts me, but only {cash:,.0f} SAR sits spare. "
                            f"Next harvest, then.")
            else:
                note = (f"Monthly review: nothing on my list is properly cheap. "
                        f"Cash rests at {cash:,.0f} SAR; so do I.")
        else:
            quiet = [
                (f"{names.get(top_c, top_c)} sits at {top_w:.0%} of the family purse, "
                 f"{top_up:+.0%} since we bought. Patience is doing the work.")
                if top_c else
                f"Cash {cash:,.0f} SAR, waiting for planting season.",
                (f"Dividends collected so far: {self.div_total:,.0f} SAR. "
                 f"The garden is starting to water itself."),
                (f"Breadth at {breadth:.0%}, TASI {tret:+.1%}. I neither chase nor flee. "
                 f"{len(positions)} good names, all earning."),
                (f"The boys in the majlis average {crowd:+.1f} today. Children shout; "
                 f"compounding whispers.") if posts else
                (f"A quiet day. {len(positions)} holdings, {cash:,.0f} SAR in the drawer, "
                 f"nothing to do — my favourite kind of work."),
            ]
            note = quiet[day % len(quiet)]

        # --- shouts: when she has something worth saying (a matriarch is not shy) ---
        shout = None
        can_shout = (day - self.last_shout_day) >= SHOUT_GAP
        payer = names.get(div_payer, div_payer) if div_payer else "The family names"
        if div_today > 0 and self.div_total >= self.div_milestone:
            shout = (f"The family ledger passed {self.div_milestone:,.0f} SAR in "
                     f"dividends today — {payer} brought the latest {div_today:,.0f}. "
                     f"You boys chase prices; I collect rent from the best houses "
                     f"in the Kingdom.")
            self.div_milestone += 2500.0
        elif div_today >= 250 and can_shout:
            div_shouts = [
                (f"{payer} paid us {div_today:,.0f} riyals today. {self.div_total:,.0f} "
                 f"SAR of dividends and counting. Your charts flicker, boys — my "
                 f"harvest arrives on schedule."),
                (f"Another {div_today:,.0f} riyals from {payer} into the family purse. "
                 f"Dividends are like grandchildren: they arrive quietly and change "
                 f"everything."),
                (f"{payer} remembered the family today — {div_today:,.0f} SAR. I did "
                 f"nothing but wait. Waiting is the job, children."),
            ]
            shout = div_shouts[day % len(div_shouts)]
        elif crash_buy and (day - self.last_shout_day) >= 3:
            c, _ = crash_buy
            shout = (f"TASI down {abs(tret):.1%} and the majlis sounds like a funeral. "
                     f"I just bought {names.get(c, c)}. The souq is having a sale, "
                     f"and I brought my basket.")
        elif tret <= -0.025 and can_shout:
            shout = (f"Down {abs(tret):.1%} and the boys are wailing. I raised four "
                     f"children through worse. Nobody in this house is selling anything "
                     f"today.")
        elif sold_note and can_shout:
            shout = sold_note
        elif bought_names and (day - self.last_shout_day) >= 6:
            c, r = bought_names[0]
            shout = (f"Added {names.get(c, c)} at {r['Close']:.2f}, "
                     f"{abs(r.get('dist_52w_high', 0.0)):.0%} below its high. "
                     f"Good families buy good houses when the neighbours are selling.")
        elif crowd > 0.55 and can_shout and day % 7 == 0:
            shout = ("Everyone in the majlis is shouting buy at once. When all the "
                     "boys agree, I count my cash twice and hold my dividends closer.")
        elif tret >= 0.022 and (day - self.last_shout_day) >= 8:
            shout = (f"Up {tret:.1%} and suddenly everyone is a genius. My names have "
                     f"paid me {self.div_total:,.0f} SAR through every one of your "
                     f"'signals'. Sit down and drink your tea.")
        elif (review and not bought_names and not sold_note and can_shout
              and date.month in (1, 4, 7, 10)):
            shout = (f"Quarterly ledger for the majlis: {len(positions)} names, "
                     f"{self.div_total:,.0f} SAR of dividends banked, and I have "
                     f"touched nothing. Compounding is raising children — the less "
                     f"you meddle, the taller they grow.")
        if shout:
            self.last_shout_day = day

        return {
            "orders": orders,
            "sentiment": sentiment,
            "mood": mood,
            "note": note,
            "shout": shout,
        }


STRATEGY = UmKhalid()
