"""AAOIFI Shariah screen over the discovered NASDAQ universe.

Reference: AAOIFI Shari'ah Standard No. 21 (Financial Papers). Four layers:

1. BUSINESS-ACTIVITY SCREEN — the core business must not be prohibited:
   conventional banking / insurance / interest-based finance, alcohol, gambling,
   pork, tobacco, adult entertainment, recreational cannabis. Implemented as a
   curated keyword screen over the NASDAQ screener's sector + industry labels
   (plus company name for a few unambiguous cases). Defense is NOT excluded
   (AAOIFI does not prohibit it); video-game companies are not excluded
   ("gaming" != gambling).

2. FINANCIAL-RATIO SCREEN — both must hold:
   - interest-bearing debt / market capitalization        < 30%
   - (cash + interest-bearing securities) / market cap    < 30%
   Data via yfinance: totalDebt, totalCash, marketCap.

3. INSTRUMENT SCREEN (added 2026-09-25, docs/07) — common shares only.
   Preferred shares (fixed or priority returns), perpetuals, warrants, units,
   rights and notes are rejected by name, whatever the issuer's ratios. The
   first screen let seven preferred lines through on their issuers' ratios.

4. CURATED OVERRIDES — data/sharia_overrides.json. "exclude" rejects names
   the keyword screen cannot see (Smithfield Foods, a pork producer labelled
   "Meat/Poultry/Fish"); "review" flags method-dependent names for the
   owner's policy decision without excluding them.

HONEST LIMITATIONS (documented, not hidden):
- The <5% impermissible-income rule is NOT computable from free data; the
  business screen is its proxy. A production system needs revenue-line data.
- Fundamentals are CURRENT-day snapshots, not point-in-time: the screen is
  applied as of the fetch date and held constant across history. That, plus
  screening today's listings, adds survivorship/lookahead bias to backtests.
- totalCash includes non-interest-bearing operating cash → our cash ratio is
  CONSERVATIVE (over-excludes rather than under-excludes).

Writes NASDAQ/data/universe_screened.json with full per-name audit trail.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / os.environ.get("SCREEN_IN", "data/universe_top.json")
OUT = ROOT / os.environ.get("SCREEN_OUT", "data/universe_screened.json")
OVERRIDES = ROOT / "data" / "sharia_overrides.json"

DEBT_MAX = 0.30   # AAOIFI: interest-bearing debt < 30% of market cap
CASH_MAX = 0.30   # AAOIFI: interest-bearing securities < 30% of market cap

# Business-activity screen: lowercase keyword → reason. Matched against
# "sector | industry" and, for a few unambiguous vices, the company name.
PROHIBITED_KEYWORDS = {
    # conventional finance (riba-based core business)
    "bank": "conventional banking",
    "savings institution": "conventional banking",
    "insurance": "conventional insurance",
    "investment banker": "interest-based finance",
    "investment broker": "interest-based finance",
    "broker": "interest-based finance",
    "finance company": "interest-based finance",
    "finance: consumer": "interest-based finance",
    "consumer loan": "interest-based finance",
    "sales financing": "interest-based finance",
    "mortgage": "interest-based finance",
    "credit service": "interest-based finance",
    "investment manager": "interest-based finance",
    "investment trust": "interest-based finance",
    "blank check": "SPAC shell (no permissible business)",
    "real estate investment trust": "REIT (interest-heavy structure)",
    "reit": "REIT (interest-heavy structure)",
    # alcohol
    "brewer": "alcohol",
    "distill": "alcohol",
    "vintner": "alcohol",
    "winer": "alcohol",
    "beverages (alcoholic)": "alcohol",
    # tobacco & recreational cannabis
    "tobacco": "tobacco",
    "cigar": "tobacco",
    "cannabis": "recreational cannabis",
    # gambling (NOT video games)
    "casino": "gambling",
    "gambling": "gambling",
    "lotter": "gambling",
    "betting": "gambling",
    "sports book": "gambling",
    # pork
    "pork": "pork",
    "meat packing": "pork exposure",
    # adult entertainment
    "adult": "adult entertainment",
}

NAME_KEYWORDS = {  # matched against company NAME only (unambiguous vices)
    "casino": "gambling", "bancorp": "conventional banking",
    "bancshares": "conventional banking", "bankshares": "conventional banking",
    "insurance": "conventional insurance",
}


def business_screen(entry) -> list[str]:
    hay = f"{entry.get('sector','')} | {entry.get('industry','')}".lower()
    reasons = [why for kw, why in PROHIBITED_KEYWORDS.items() if kw in hay]
    name = entry.get("name", "").lower()
    reasons += [why for kw, why in NAME_KEYWORDS.items() if kw in name]
    return sorted(set(reasons))


# Instrument screen: the listing must be a common share. Matched against the
# security NAME (the screener spells out "Preferred Stock", "Warrants", ...).
# American Depositary Shares of common equity stay in: only depositary
# interests in PREFERRED stock carry the word "Preferred".
INSTRUMENT_PATTERNS = [
    (re.compile(r"\bpreferred\b", re.I),
     "preferred shares: priority or fixed returns (AAOIFI SS 21 accepts common shares only)"),
    (re.compile(r"\bperpetual\b", re.I), "perpetual fixed-income instrument"),
    (re.compile(r"\bwarrants?\b", re.I), "warrant, not a share"),
    (re.compile(r"\bunits?\b", re.I), "unit (bundled instrument), not a share"),
    (re.compile(r"\brights?\b", re.I), "subscription right, not a share"),
    (re.compile(r"\bnotes? due\b|\bdebentures?\b", re.I), "debt security"),
]

# Review flags: method-dependent activities. They do NOT fail the screen;
# they mark names for the owner's written policy (docs/07, decision D1).
# Industry labels are shared across unlike businesses (auto dealers file under
# "Gas Stations", chip makers under "Broadcasting ... Equipment"), so only
# unambiguous labels flag here; the rest are named in the overrides file.
REVIEW_PATTERNS = [
    (re.compile(r"meat/poultry/fish", re.I), "meat processing: confirm no pork"),
    (re.compile(r"hotels/resorts", re.I), "hotels: bar and entertainment revenue"),
    (re.compile(r"amusement", re.I), "entertainment venues"),
    (re.compile(r"broadcasting(?!.*equipment)", re.I), "broadcasting and entertainment content"),
]


def load_overrides() -> dict:
    if OVERRIDES.exists():
        return json.loads(OVERRIDES.read_text())
    return {"exclude": {}, "review": {}}


def instrument_screen(entry) -> list[str]:
    name = entry.get("name", "")
    return sorted({why for pat, why in INSTRUMENT_PATTERNS if pat.search(name)})


def override_screen(entry, overrides: dict) -> list[str]:
    why = (overrides.get("exclude") or {}).get(entry["code"])
    return [why] if why else []


def review_flags(entry, overrides: dict) -> list[str]:
    hay = f"{entry.get('sector','')} | {entry.get('industry','')}"
    flags = {why for pat, why in REVIEW_PATTERNS if pat.search(hay)}
    why = (overrides.get("review") or {}).get(entry["code"])
    if why:
        flags.add(why)
    return sorted(flags)


def apply_rule_layers(record: dict, overrides: dict) -> dict:
    """Instrument, curated-exclusion and review layers; no network needed."""
    record["instrument_reasons"] = instrument_screen(record)
    record["override_reasons"] = override_screen(record, overrides)
    record["review_flags"] = review_flags(record, overrides)
    record["pass"] = bool(record.get("business_pass")) and bool(record.get("ratios_pass")) \
        and not record["instrument_reasons"] and not record["override_reasons"]
    return record


def fetch_fundamentals(sym: str):
    import yfinance as yf

    t = yf.Ticker(sym)
    info = {}
    try:
        info = t.get_info() or {}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "Rate" in msg or "Too Many" in msg or "429" in msg:
            print(f"  rate limited on {sym}; cooling 75s", file=sys.stderr)
            time.sleep(75)
            try:
                info = t.get_info() or {}
            except Exception:  # noqa: BLE001
                info = {}
    mcap = info.get("marketCap")
    if not mcap:
        try:
            mcap = t.fast_info.market_cap
        except Exception:  # noqa: BLE001
            mcap = None
    return {
        "mcap": float(mcap) if mcap else None,
        "total_debt": float(info["totalDebt"]) if info.get("totalDebt") is not None else None,
        "total_cash": float(info["totalCash"]) if info.get("totalCash") is not None else None,
        "sector_yf": info.get("sector"),
        "industry_yf": info.get("industry"),
    }


def main() -> int:
    uni = json.loads(IN.read_text())["universe"]
    max_names = int(os.environ.get("SCREEN_MAX", "500"))
    uni = uni[:max_names]
    overrides = load_overrides()
    passed, rejected = [], []

    for i, e in enumerate(uni):
        sym = e["code"]
        record = dict(e)

        # yfinance sector/industry supplements the screener's labels
        f = fetch_fundamentals(sym)
        record.update(f)
        if f.get("sector_yf"):
            e = {**e, "sector": f"{e.get('sector','')} {f['sector_yf']}",
                 "industry": f"{e.get('industry','')} {f['industry_yf'] or ''}"}

        reasons = business_screen(e)
        record["business_reasons"] = reasons
        record["business_pass"] = not reasons

        mcap = f["mcap"] or e.get("mcap") or 0
        debt = f["total_debt"]
        cash = f["total_cash"]
        record["debt_ratio"] = round(debt / mcap, 4) if (debt is not None and mcap) else None
        record["cash_ratio"] = round(cash / mcap, 4) if (cash is not None and mcap) else None

        ratio_reasons = []
        if not mcap:
            ratio_reasons.append("no market cap data")
        if record["debt_ratio"] is not None and record["debt_ratio"] >= DEBT_MAX:
            ratio_reasons.append(f"debt/mcap {record['debt_ratio']:.0%} >= 30%")
        if record["cash_ratio"] is not None and record["cash_ratio"] >= CASH_MAX:
            ratio_reasons.append(f"cash/mcap {record['cash_ratio']:.0%} >= 30%")
        if debt is None:
            ratio_reasons.append("no debt data")
        record["ratio_reasons"] = ratio_reasons
        record["ratios_pass"] = not ratio_reasons

        apply_rule_layers(record, overrides)
        (passed if record["pass"] else rejected).append(record)

        if (i + 1) % 25 == 0:
            print(f"[{i+1}/{len(uni)}] screened; {len(passed)} pass so far", file=sys.stderr)
            time.sleep(3)
        time.sleep(0.35)

    OUT.write_text(json.dumps({
        "reference": "AAOIFI Shari'ah Standard No. 21 (approximated; see docstring)",
        "thresholds": {"debt_over_mcap_max": DEBT_MAX, "cash_over_mcap_max": CASH_MAX,
                       "impermissible_income_max": "5% (proxied by business screen; not computable from free data)"},
        "screened": len(uni), "passed": len(passed), "rejected": len(rejected),
        "universe": passed,
        "rejected_detail": rejected,
    }, ensure_ascii=False, indent=1))
    print(f"screened {len(uni)}: {len(passed)} pass AAOIFI, {len(rejected)} rejected")
    if len(passed) < 100:
        print("ERROR: fewer than 100 survivors — inspect rejected_detail", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
