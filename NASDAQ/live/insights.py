"""Insights step (docs/08 §6): confidence ratings, stop levels and prices for
every holding, written to ledger/insights/<asof>.json after the twin.

The strategy file stays frozen. This wrapper re-uses its *pure* pieces
read-only — `_score()` for the momentum rank, its constants and the twin's
current parameters — and reconstructs the exit levels exactly as decide()
places them:

* initial stop  = AdjClose on the entry decision day − STOP_ATR × ATR(14) then
* trailing stop = highest AdjClose since the fill − TRAIL_ATR × ATR(14) today,
                  armed once the peak is TRAIL_ARM (+10%) above the entry
* trend break   = the 200-day average;  hard stop = −20% from average cost
* rank exit     = out of the top max(TARGET_N + 2, TARGET_N × RANK_BUFFER)
* time stop     = TIME_STOP sessions held while under water

Levels are converted from the adjusted to the raw price basis of the day, so
they compare with the last close the console shows.

Confidence = Signal 40% · Risk room 30% · Regime 20% · Data 10% (0–100 each).
It is labelled "model conviction, not a forecast" and never feeds back into
trading. Nothing here can change an order.

Usage (Cycle A calls build() in-process):
  python NASDAQ/live/insights.py --asof 2026-09-25 [--out path]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import pandas as pd

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402

PRICE_SESSIONS = 260
WEIGHTS = (0.40, 0.30, 0.20, 0.10)


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def load_strategy_module():
    spec = importlib.util.spec_from_file_location("strategies.insights_agent", config.AGENT_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PKG / "sim"))
    spec.loader.exec_module(mod)
    return mod


def load_frames(enriched: Path, codes: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for c in codes:
        f = enriched / f"{c}.csv"
        if f.exists():
            out[c] = pd.read_csv(f, index_col="Date", parse_dates=True)
    return out


def _row(df: pd.DataFrame, day: pd.Timestamp) -> dict | None:
    if day not in df.index:
        return None
    r = df.loc[day]
    return {k: (float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None) for k, v in r.items()}


def liquidity(frames: dict[str, pd.DataFrame], start: pd.Timestamp, day: pd.Timestamp, alpha: float) -> dict[str, float]:
    """The strategy's causal turnover EMA, replayed from the twin's start."""
    out = {}
    for c, df in frames.items():
        if c == "IXIC" or "turnover_sar" not in df:
            continue
        s = df.loc[(df.index >= start) & (df.index <= day), "turnover_sar"].dropna()
        s = s[s >= 0]
        if s.empty:
            continue
        prev = None
        for t in s.to_numpy():
            prev = t if prev is None else prev + alpha * (t - prev)
        out[c] = float(prev)
    return out


def ranking(mod, strat, frames, day: pd.Timestamp, turn: dict[str, float]) -> dict[str, int]:
    """1-based momentum rank on `day`, filtered like decide()."""
    rows = []
    for c, df in frames.items():
        if c == mod.BENCH:
            continue
        r = _row(df, day)
        if not r:
            continue
        px, raw = r.get("AdjClose"), r.get("Close")
        if not _ok(px) or px <= 0 or not _ok(raw) or raw < mod.PX_MIN:
            continue
        if turn.get(c) is None or turn[c] < mod.LIQ_MIN:
            continue
        s = strat._score(r)
        if s is None:
            continue
        rows.append((s[0], c))
    rows.sort(key=lambda t: (-t[0], t[1]))
    return {c: i + 1 for i, (_, c) in enumerate(rows)}


def regime_dial(mod, frames, day: pd.Timestamp) -> tuple[float, dict]:
    """decide()'s continuous regime dial in [0, 1], with its inputs."""
    b = _row(frames.get(mod.BENCH, pd.DataFrame()), day) if mod.BENCH in frames else None
    g200 = g50 = 0.5
    info: dict = {}
    if b and _ok(b.get("AdjClose")):
        bc = b["AdjClose"]
        if _ok(b.get("sma200")) and b["sma200"] > 0:
            info["ixic_vs_sma200"] = round(bc / b["sma200"] - 1, 4)
            g200 = mod._ramp(bc / b["sma200"] - 1.0, mod.R200_LO, mod.R200_HI)
        if _ok(b.get("sma50")) and b["sma50"] > 0:
            info["ixic_vs_sma50"] = round(bc / b["sma50"] - 1, 4)
            g50 = mod._ramp(bc / b["sma50"] - 1.0, mod.R50_LO, mod.R50_HI)
    above = valid = 0
    for c, df in frames.items():
        if c == mod.BENCH:
            continue
        r = _row(df, day)
        if r and _ok(r.get("sma50")) and _ok(r.get("AdjClose")):
            valid += 1
            above += r["AdjClose"] > r["sma50"]
    breadth = above / valid if valid else 0.5
    info["breadth"] = round(breadth, 4)
    gbr = mod._ramp(breadth, mod.BR_LO, mod.BR_HI)
    return 0.40 * g200 + 0.30 * g50 + 0.30 * gbr, info


def sma_stack(r: dict) -> str | None:
    px, s50, s100, s200 = (r.get(k) for k in ("AdjClose", "sma50", "sma100", "sma200"))
    if not all(_ok(x) for x in (px, s50, s100, s200)):
        return None
    above = [n for n, s in (("50", s50), ("100", s100), ("200", s200)) if px > s]
    below = [n for n, s in (("50", s50), ("100", s100), ("200", s200)) if px <= s]
    if not below:
        return "above SMA 50, 100 and 200"
    if not above:
        return "below SMA 50, 100 and 200"
    return "above SMA " + " and ".join(above) + ", below SMA " + " and ".join(below)


def signal_score(rank: int | None, rank_cut: int, r: dict) -> int:
    s_rank = 100 * _clamp(1 - (rank - 1) / (2 * rank_cut), 0, 1) if rank else 0.0
    px, s50, s100, s200 = (r.get(k) for k in ("AdjClose", "sma50", "sma100", "sma200"))
    if all(_ok(x) for x in (px, s50, s100, s200)) and s50 > s100 > s200 and px > s50:
        s_stack = 100.0
    elif _ok(px) and _ok(s200) and px > s200:
        s_stack = 60.0
    else:
        s_stack = 0.0
    d52 = r.get("dist_52w_high")
    s_high = 100 * _clamp(1 + d52 * 4, 0, 1) if _ok(d52) else 50.0
    return round(0.6 * s_rank + 0.2 * s_stack + 0.2 * s_high)


def risk_score(dist_atr: float | None, held: int, time_stop: float, under_water: bool) -> int:
    d = 100 * _clamp((dist_atr or 0.0) / 4.0, 0, 1) if dist_atr is not None else 50.0
    t = 100 * _clamp((time_stop - held) / time_stop, 0, 1) if under_water else 100.0
    return round(0.8 * d + 0.2 * t)


def data_score(gate: dict | None, code: str) -> tuple[int, str | None]:
    if not gate:
        return 50, None
    if gate.get("status") == "trip":
        return 15, None
    xs = (gate.get("checks") or {}).get("cross_source") or {}
    if any(d.get("code") == code for d in xs.get("disagreements") or []):
        return 20, "disagree"
    if code in (xs.get("agreed") or []):
        return 100, "agree"
    return 70, "unavailable"


def holding_start(trades: list[dict], code: str) -> str | None:
    pos, start = 0, None
    for t in trades:
        if t.get("code") != code:
            continue
        n = int(t.get("shares") or 0)
        if t.get("side") == "buy":
            if pos == 0:
                start = t.get("date")
            pos += n
        else:
            pos -= n
            if pos <= 0:
                pos, start = 0, None
    return start


def build(asof: str, twin: dict, frames: dict[str, pd.DataFrame], gate: dict | None, mod=None) -> dict:
    mod = mod or load_strategy_module()
    strat = mod.Trend()
    for k, v in (twin.get("params") or {}).items():
        if hasattr(strat, k):
            setattr(strat, k, float(v))
    day = pd.Timestamp(asof)
    start = pd.Timestamp(twin.get("live_start") or asof)
    rank_cut = max(mod.TARGET_N + 2, int(mod.TARGET_N * strat.RANK_BUFFER))
    turn = liquidity(frames, start, day, mod.TURN_ALPHA)
    ranks = ranking(mod, strat, frames, day, turn)
    dial, regime_info = regime_dial(mod, frames, day)
    regime = round(100 * dial)
    positions: dict = {}
    prices: dict = {}
    for code, p in (twin.get("positions") or {}).items():
        df = frames.get(code)
        if df is None or day not in df.index:
            continue
        r = _row(df, day)
        fill = holding_start(twin.get("trades") or [], code)
        idx = df.index
        fill_ts = pd.Timestamp(fill) if fill else day
        before = idx[idx < fill_ts]
        dec_day = before[-1] if len(before) else fill_ts
        r0 = _row(df, dec_day) or {}
        e0, a0 = r0.get("AdjClose"), r0.get("atr14")
        adj = r.get("AdjClose")
        raw = r.get("Close")
        basis = raw / adj if (_ok(raw) and _ok(adj) and adj) else 1.0
        atr = r.get("atr14")
        initial = (e0 - strat.STOP_ATR * a0) * basis if _ok(e0) and _ok(a0) else None
        since = df.loc[(idx >= fill_ts) & (idx <= day), "AdjClose"].dropna()
        peak = float(since.max()) if not since.empty else None
        trailing = None
        if _ok(peak) and _ok(e0) and e0 > 0 and _ok(atr) and peak / e0 - 1 >= mod.TRAIL_ARM:
            trailing = (peak - strat.TRAIL_ATR * atr) * basis
        avg = float(p.get("avg_cost") or 0)
        hard = avg * (1 + mod.HARD_STOP) if avg else None
        s200 = r.get("sma200") * basis if _ok(r.get("sma200")) else None
        price = float(p.get("price") or raw or 0)
        levels = [(k, v) for k, v in (("initial", initial), ("trailing", trailing), ("hard", hard), ("sma200", s200)) if _ok(v) and v < price]
        nearest = max(levels, key=lambda t: t[1]) if levels else None
        atr_raw = atr * basis if _ok(atr) else None
        dist = (price - nearest[1]) / atr_raw if (nearest and atr_raw) else None
        held = int(((idx >= fill_ts) & (idx <= day)).sum())
        rank = ranks.get(code)
        under = price < avg
        d52 = r.get("dist_52w_high")
        data, xs = data_score(gate, code)
        sig = signal_score(rank, rank_cut, r)
        risk = risk_score(dist, held, strat.TIME_STOP, under)
        # conviction at the entry decision, from the same inputs that day
        turn0 = liquidity(frames, start, dec_day, mod.TURN_ALPHA) if dec_day != day else turn
        rank0 = ranking(mod, strat, frames, dec_day, turn0).get(code) if dec_day != day else rank
        sig0 = signal_score(rank0, rank_cut, r0) if r0 else sig
        reg0 = round(100 * regime_dial(mod, frames, dec_day)[0]) if dec_day != day else regime
        at_entry = round(WEIGHTS[0] * sig0 + WEIGHTS[1] * risk_score(strat.STOP_ATR, 0, strat.TIME_STOP, False) + WEIGHTS[2] * reg0 + WEIGHTS[3] * 100)
        positions[code] = {
            "signal": sig, "risk_room": risk, "regime": regime, "data": data, "at_entry": at_entry,
            "overall": round(WEIGHTS[0] * sig + WEIGHTS[1] * risk + WEIGHTS[2] * regime + WEIGHTS[3] * data),
            "atr": round(atr_raw, 4) if atr_raw else None,
            "initial_stop": round(initial, 4) if _ok(initial) else None,
            "trailing_stop": round(trailing, 4) if _ok(trailing) else None,
            "hard_stop": round(hard, 4) if _ok(hard) else None,
            "sma200": round(s200, 4) if _ok(s200) else None,
            "nearest_exit": {"kind": nearest[0], "level": round(nearest[1], 4), "atr_away": round(dist, 2) if dist is not None else None} if nearest else None,
            "high": round(price / (1 + d52), 4) if _ok(d52) and d52 > -1 else None,
            "off_high_pct": round(-d52 * 100) if _ok(d52) else None,
            "rank": rank, "rank_cut": rank_cut,
            "sma_stack": sma_stack(r),
            "cross_source": xs,
            "held_sessions": held,
            "fill_date": fill,
        }
        tail = df.loc[df.index <= day, "Close"].dropna().tail(PRICE_SESSIONS)
        prices[code] = [[d.date().isoformat(), round(float(v), 4)] for d, v in tail.items()]
    return {
        "asof": asof, "agent": twin.get("agent"), "weights": {"signal": 0.4, "risk_room": 0.3, "regime": 0.2, "data": 0.1},
        "note": "model conviction, not a forecast",
        "regime": {"score": regime, **regime_info, "mood": ((twin.get("journal") or [{}])[-1]).get("mood")},
        "universe_ranked": len(ranks),
        "positions": positions,
        "prices": prices,
    }


def write(asof: str, twin: dict, gate: dict | None, ledger: Path, enriched: Path | None = None) -> Path:
    enriched = enriched or PKG / os.environ.get("TWIN_ENRICHED_SUBDIR", config.ENRICHED_SUBDIR)
    universe = [u["code"] for u in json.loads((PKG / "data" / "universe_screened.json").read_text())["universe"]]
    codes = sorted(set(universe) | set(twin.get("positions") or {}) | {"IXIC"})
    doc = build(asof, twin, load_frames(enriched, codes), gate)
    out = ledger / "insights" / f"{asof}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True)
    args = ap.parse_args()
    twin = json.loads((config.LEDGER / "twin" / "twin_latest.json").read_text())
    rec_path = config.LEDGER / "cycles" / f"{args.asof}-A.json"
    gate = json.loads(rec_path.read_text()).get("data_gate") if rec_path.exists() else None
    out = write(args.asof, twin, gate, config.LEDGER)
    print(f"insights: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
