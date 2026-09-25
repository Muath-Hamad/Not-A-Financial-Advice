"""Harness guardrails (docs/05 §7.2) — enforced outside the agent.

Every order the twin queues is checked against declared limits before it can
leave the harness: AAOIFI whitelist and manual exclusions, long-only, per-name
weight cap, daily turnover cap, and an order-size sanity cap against the
name's average daily dollar volume.

Ghost mode is report-only: violations are recorded and alerted, because the
ghost ledger must mirror the twin exactly. In paper mode (Phase 2) the same
checks filter what is actually submitted to the broker.
"""

from __future__ import annotations

import sys
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402


def _est_value(od: dict, equity: float, close: float | None, held_value: float) -> float | None:
    """Best-effort dollar size of an order before its fill price exists."""
    if od["side"] == "buy":
        if od.get("sar") is not None:
            return float(od["sar"])
        if od.get("weight") is not None:
            return float(od["weight"]) * equity
        if od.get("shares") is not None and close:
            return float(od["shares"]) * close
        return None
    if od.get("all"):
        return held_value
    if od.get("fraction") is not None:
        return held_value * max(0.0, min(1.0, float(od["fraction"])))
    if od.get("shares") is not None and close:
        return float(od["shares"]) * close
    if od.get("sar") is not None:
        return float(od["sar"])
    return held_value


def check_orders(orders: list[dict], twin: dict, refs: dict, universe: set[str],
                 controls: dict) -> dict:
    """refs: {code: {"close": float, "adv_dollars": float}} at asof."""
    equity = twin["equity_final"]
    positions = twin["positions"]
    violations, checked = [], []
    buy_total = sell_total = 0.0

    for od in orders:
        code, side = od["code"], od["side"]
        ref = refs.get(code, {})
        held_value = positions.get(code, {}).get("value", 0.0)
        est = _est_value(od, equity, ref.get("close"), held_value)
        entry = {"code": code, "side": side, "est_value": round(est, 2) if est else None}

        if code not in universe:
            violations.append({**entry, "rule": "whitelist",
                               "detail": "not in the AAOIFI-screened universe"})
        if code in set(controls.get("excluded_symbols") or []):
            violations.append({**entry, "rule": "excluded",
                               "detail": "manually excluded via controls.json"})
        if side == "buy" and controls.get("pause_entries"):
            violations.append({**entry, "rule": "pause_entries",
                               "detail": "new entries paused via controls.json"})
        if side not in ("buy", "sell"):
            violations.append({**entry, "rule": "long_only", "detail": f"side {side!r}"})
        if side == "sell" and code not in positions:
            violations.append({**entry, "rule": "long_only",
                               "detail": "sell of a name the book does not hold"})

        if est is not None:
            if side == "buy":
                buy_total += est
                w = (held_value + est) / equity if equity > 0 else 1.0
                if w > config.MAX_POS_WEIGHT:
                    violations.append({**entry, "rule": "max_pos_weight",
                                       "detail": f"would be {w:.1%} > {config.MAX_POS_WEIGHT:.0%}"})
            else:
                sell_total += est
            adv = ref.get("adv_dollars")
            if adv and est > config.ADV_CAP * adv:
                violations.append({**entry, "rule": "adv_cap",
                                   "detail": f"{est:,.0f} > {config.ADV_CAP:.0%} of ADV {adv:,.0f}"})
        checked.append(entry)

    turnover = (buy_total + sell_total) / equity if equity > 0 else 0.0
    if turnover > config.MAX_DAILY_TURNOVER:
        violations.append({"rule": "max_daily_turnover", "code": None, "side": None,
                           "detail": f"{turnover:.1%} > {config.MAX_DAILY_TURNOVER:.0%}"})

    gross_cap = controls.get("gross_cap")
    if gross_cap is not None:
        pos_value = sum(p["value"] for p in positions.values())
        gross_after = (pos_value + buy_total - sell_total) / equity if equity > 0 else 0.0
        if gross_after > float(gross_cap):
            violations.append({"rule": "gross_cap", "code": None, "side": None,
                               "detail": f"gross would be {gross_after:.1%} > cap {float(gross_cap):.0%}"})

    return {"n_orders": len(orders), "checked": checked,
            "buy_total": round(buy_total, 2), "sell_total": round(sell_total, 2),
            "turnover": round(turnover, 4), "violations": violations}
