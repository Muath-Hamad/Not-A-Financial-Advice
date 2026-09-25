"""Pure execution rules shared by the submit step and the reconciliation
cycles (docs/07).

Nothing here does I/O: every function takes plain data and returns plain
data, so the rules that decide what reaches the broker, and what counts as a
reconciliation break, are unit-tested (NASDAQ/tests/).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from broker import client_order_id, to_share_order  # noqa: E402


def in_submit_window(now_et: dt.datetime) -> bool:
    """Alpaca accepts on-open orders after 19:00 ET and before 09:28 ET."""
    t = (now_et.hour, now_et.minute)
    return t >= config.SUBMIT_OPENS_ET or t < config.SUBMIT_CUTOFF_ET


def broker_holdings(positions: list | None) -> dict[str, int]:
    """Alpaca /v2/positions -> {symbol: whole shares held (long only)}."""
    out: dict[str, int] = {}
    for p in positions or []:
        try:
            qty = int(float(p.get("qty", 0)))
        except (TypeError, ValueError):
            continue
        if qty:
            out[str(p.get("symbol"))] = qty
    return out


def _order_fields(entry: dict) -> dict:
    return {k: entry.get(k) for k in ("code", "side", "sar", "weight", "shares",
                                      "fraction", "all")}


def plan_submissions(asof: str, entries: list[dict], held: dict[str, int],
                     closes: dict[str, float | None], cash: float, equity: float,
                     excluded: set[str], slippage: float) -> dict:
    """Decide exactly what tonight's submit step sends.

    * Blocked entries (guardrail violations) are skipped.
    * Sells are sized from the shares the ACCOUNT holds, never the twin's
      count, so the harness cannot try to sell shares it does not have.
    * Every account-held name on the exclusion list gets a forced exit,
      even when the ledger (the twin's view) has no sell for it; a partial
      sell of an excluded name becomes a full exit.
    * Buys keep their ledgered size unless the night's buys would spend more
      than the cash the account will have after tonight's sells; then the
      last buys are trimmed or dropped, so no order leans on margin.
    """
    sells: list[dict] = []
    buys: list[dict] = []
    skipped: list[dict] = []
    adjusted: list[dict] = []

    sell_codes = set()
    for e in entries:
        code, side = e["code"], e["side"]
        if e.get("blocked"):
            skipped.append({"code": code, "side": side, "client_order_id": e.get("client_order_id"),
                            "reason": "blocked: " + ", ".join(e["blocked"])})
            continue
        if side == "sell":
            have = held.get(code, 0)
            if have <= 0:
                skipped.append({"code": code, "side": side,
                                "client_order_id": e.get("client_order_id"),
                                "reason": "not held at the broker"})
                continue
            # an excluded name leaves in full, even when the twin only trims it
            so = {"qty": have} if code in excluded else \
                to_share_order(_order_fields(e), equity, closes.get(code), have)
            if so is None:
                skipped.append({"code": code, "side": side,
                                "client_order_id": e.get("client_order_id"),
                                "reason": "rounds to zero shares"})
                continue
            sells.append({"code": code, "side": "sell", "qty": so["qty"],
                          "client_order_id": e["client_order_id"],
                          "forced": bool(e.get("forced")) or code in excluded})
            sell_codes.add(code)
        elif side == "buy":
            prev = e.get("share_preview") or {}
            qty = int(prev.get("qty") or 0)
            if qty < 1:
                skipped.append({"code": code, "side": side,
                                "client_order_id": e.get("client_order_id"),
                                "reason": "no share estimate (missing close)"})
                continue
            buys.append({"code": code, "side": "buy", "qty": qty,
                         "client_order_id": e["client_order_id"], "forced": False})

    # forced exits for account-held names that are excluded but have no sell yet
    for code in sorted(set(held) & set(excluded)):
        if code in sell_codes:
            continue
        od = {"code": code, "side": "sell", "all": True}
        sells.append({"code": code, "side": "sell", "qty": held[code],
                      "client_order_id": client_order_id(asof, od), "forced": True})
        sell_codes.add(code)

    # cash check: sells fill in the same auction; buys may not exceed the proceeds
    budget = cash - config.CASH_BUFFER * equity
    for s in sells:
        px = closes.get(s["code"])
        if px:
            budget += s["qty"] * px * (1.0 - slippage)
    kept: list[dict] = []
    for b in buys:
        px = closes.get(b["code"])
        if not px:
            skipped.append({"code": b["code"], "side": "buy",
                            "client_order_id": b["client_order_id"], "reason": "no close"})
            continue
        unit = px * (1.0 + slippage)
        affordable = int(max(0.0, budget) // unit)
        if affordable < b["qty"]:
            adjusted.append({"code": b["code"], "from": b["qty"], "to": affordable,
                             "reason": "cash after tonight's sells"})
            if affordable < 1:
                skipped.append({"code": b["code"], "side": "buy",
                                "client_order_id": b["client_order_id"],
                                "reason": "no cash left after earlier buys"})
                continue
            b = {**b, "qty": affordable}
        budget -= b["qty"] * unit
        kept.append(b)

    return {"submit": sells + kept, "skipped": skipped, "adjusted": adjusted,
            "cash_left_estimate": round(budget + config.CASH_BUFFER * equity, 2)}


def expected_positions(before: dict[str, int], fills: list[dict]) -> dict[str, int]:
    """Holdings the account should show after tonight's orders filled.

    fills: [{symbol, side, filled_qty}] for every submitted order (0 if unfilled).
    """
    out = dict(before)
    for f in fills:
        q = int(float(f.get("filled_qty") or 0))
        if not q:
            continue
        sym = f["symbol"]
        out[sym] = out.get(sym, 0) + (q if f["side"] == "buy" else -q)
        if out[sym] == 0:
            out.pop(sym)
    return out


def diff_positions(expected: dict[str, int], actual: dict[str, int]) -> list[dict]:
    """Every symbol whose share count differs. Any entry is an unexplained break."""
    diffs = []
    for sym in sorted(set(expected) | set(actual)):
        e, a = expected.get(sym, 0), actual.get(sym, 0)
        if e != a:
            diffs.append({"symbol": sym, "expected": e, "actual": a, "diff": a - e})
    return diffs


def drift_vs_twin(twin_positions: dict, held: dict[str, int],
                  prices: dict[str, float | None], equity: float,
                  explained: set[str] | frozenset = frozenset()) -> dict:
    """Compare the model's book with the account's, name by name.

    Small differences are expected (whole shares estimated from the prior
    close; see docs/06). A name breaches when it is off by more than
    DRIFT_SHARES_TOL shares AND more than DRIFT_PCT_TOL of its size.
    Names in `explained` (excluded symbols the account was forced out of
    while the twin, whose universe is frozen, still holds them) are listed
    but never breach and do not count toward the gap.
    """
    rows, breaches = [], []
    gap_value = 0.0
    for sym in sorted(set(twin_positions) | set(held)):
        t = int((twin_positions.get(sym) or {}).get("shares", 0))
        a = held.get(sym, 0)
        if t == a:
            continue
        d = a - t
        row = {"symbol": sym, "twin": t, "account": a, "diff": d}
        if sym in explained:
            rows.append({**row, "explained": "excluded symbol: forced exit"})
            continue
        px = prices.get(sym) or (twin_positions.get(sym) or {}).get("price") or 0.0
        gap_value += abs(d) * float(px or 0.0)
        rows.append(row)
        if abs(d) > config.DRIFT_SHARES_TOL and abs(d) > config.DRIFT_PCT_TOL * max(t, a, 1):
            breaches.append(row)
    return {"names": rows, "breaches": breaches,
            "gap_share": round(gap_value / equity, 4) if equity > 0 else None}
