"""Confidence calibration on the out-of-sample record (docs/08 §6).

Every position the elected agent held out of sample (out/results_oos.json),
on every session it was held, is scored with the insights formula — the same
frozen scoring and the parameters in force that day (adaptations applied in
order). Per band we measure how often the position rose over the next 20
sessions (or to its exit), its average return, and how often the whole trade
ended in profit. The console shows this next to every rating, so "High"
means "this is how High-rated holdings did out of sample", not a promise.

Usage: python NASDAQ/live/calibration.py   →  out/confidence_calibration.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
import insights as ins  # noqa: E402

BANDS = (("high", 70, 101), ("med", 40, 70), ("low", 0, 40))


def ema_turnover(frames: dict[str, pd.DataFrame], start: pd.Timestamp, alpha: float) -> dict[str, pd.Series]:
    out = {}
    for c, df in frames.items():
        if "turnover_sar" not in df:
            continue
        s = df.loc[df.index >= start, "turnover_sar"].where(lambda x: x >= 0)
        out[c] = s.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()
    return out


HORIZON = 20


def main() -> int:
    res = json.loads((PKG / "out" / "results_oos.json").read_text())
    agent = next(a for a in res["agents"] if a["meta"]["handle"] == config.AGENT_HANDLE)
    mod = ins.load_strategy_module()
    strat = mod.Trend()
    defaults = {k: getattr(strat, k) for k in ("EXP_MAX", "RISK_PER_TRADE", "STOP_ATR", "TRAIL_ATR", "TIME_STOP", "RANK_BUFFER", "TARGET_VOL", "W3", "W6", "W12")}
    codes = sorted(res["meta"]["names"]) + ["IXIC"]
    frames = ins.load_frames(PKG / "data" / "enriched_full", codes)
    start = pd.Timestamp(res["meta"]["sim_start"])
    days = frames["IXIC"].index[frames["IXIC"].index >= start]
    turn_df = pd.DataFrame({c: s for c, s in ema_turnover(frames, start, mod.TURN_ALPHA).items()}).reindex(days).ffill()
    adapts = sorted(agent.get("adaptations") or [], key=lambda a: a["date"])

    def params_on(day: pd.Timestamp) -> None:
        for k, v in defaults.items():
            setattr(strat, k, v)
        for a in adapts:
            if a["date"] <= day.date().isoformat():
                for k, v in a["changes"].items():
                    if hasattr(strat, k):
                        setattr(strat, k, float(v))

    rank_cache: dict = {}
    regime_cache: dict = {}

    def rank_on(day):
        if day not in rank_cache:
            params_on(day)
            row = turn_df.loc[day]
            rank_cache[day] = ins.ranking(mod, strat, frames, day, {c: float(v) for c, v in row.items() if v == v})
        return rank_cache[day]

    def regime_on(day):
        if day not in regime_cache:
            regime_cache[day] = round(100 * ins.regime_dial(mod, frames, day)[0])
        return regime_cache[day]

    samples, entries = [], []
    for t in agent["trades"]:
        if t["side"] != "sell" or not t.get("held_since") or t.get("realized_pnl") is None:
            continue
        code = t["code"]
        df = frames.get(code)
        if df is None:
            continue
        fill, exit_ = pd.Timestamp(t["held_since"]), pd.Timestamp(t["date"])
        before = days[days < fill]
        if not len(before):
            continue
        dec = before[-1]
        r0 = ins._row(df, dec) or {}
        e0, a0 = r0.get("AdjClose"), r0.get("atr14")
        if not (ins._ok(e0) and ins._ok(a0)):
            continue
        n = int(t["shares"]) or 1
        entry_px = float(t["price"]) - float(t["realized_pnl"]) / n
        won = float(t["realized_pnl"]) > 0
        held_days = [d for d in df.index if fill <= d < exit_]
        closes = df["AdjClose"]
        peak = None
        for k, day in enumerate(held_days):
            params_on(day)
            rank_cut = max(mod.TARGET_N + 2, int(mod.TARGET_N * strat.RANK_BUFFER))
            r = ins._row(df, day)
            px, atr = r.get("AdjClose"), r.get("atr14")
            if not (ins._ok(px) and ins._ok(atr)) or atr <= 0:
                continue
            peak = px if peak is None else max(peak, px)
            levels = [e0 - strat.STOP_ATR * a0, entry_px * (1 + mod.HARD_STOP) * (px / (r.get("Close") or px))]
            if peak / e0 - 1 >= mod.TRAIL_ARM:
                levels.append(peak - strat.TRAIL_ATR * atr)
            if ins._ok(r.get("sma200")):
                levels.append(r["sma200"])
            below = [x for x in levels if x < px]
            dist = (px - max(below)) / atr if below else 0.0
            sig = ins.signal_score(rank_on(day).get(code), rank_cut, r)
            risk = ins.risk_score(dist, k, strat.TIME_STOP, px < e0)
            conf = round(ins.WEIGHTS[0] * sig + ins.WEIGHTS[1] * risk + ins.WEIGHTS[2] * regime_on(day) + ins.WEIGHTS[3] * 100)
            j = days.get_indexer([day])[0]
            fwd_day = days[min(j + HORIZON, len(days) - 1)]
            fwd_day = min(fwd_day, exit_)
            fwd = closes.loc[:fwd_day].dropna()
            ret = float(fwd.iloc[-1] / px - 1) if not fwd.empty else 0.0
            samples.append({"conf": conf, "fwd": ret, "won": won})
            if k == 0:
                entries.append(conf)

    bands = []
    for name, lo, hi in BANDS:
        rs = [x for x in samples if lo <= x["conf"] < hi]
        bands.append({"band": name, "n": len(rs),
                      "hit_rate": round(sum(x["fwd"] > 0 for x in rs) / len(rs), 4) if rs else None,
                      "avg_return": round(sum(x["fwd"] for x in rs) / len(rs), 4) if rs else None,
                      "trade_won_rate": round(sum(x["won"] for x in rs) / len(rs), 4) if rs else None})
    out = {"agent": config.AGENT_HANDLE, "window": [res["meta"]["sim_start"], res["meta"]["sim_end"]],
           "horizon_sessions": HORIZON, "position_days": len(samples), "round_trips": len(entries),
           "entry_bands": {b: sum(1 for c in entries if lo <= c < hi) for b, lo, hi in BANDS},
           "method": ("every held position on every out-of-sample session scored with the insights formula (frozen scoring, the "
                      "parameters in force that day, data = 100); outcome = the position's return over the next 20 sessions "
                      "(or to its exit), and whether the whole trade ended in profit"),
           "bands": bands}
    path = PKG / "out" / "confidence_calibration.json"
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
