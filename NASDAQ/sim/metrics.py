"""Performance metrics for agent equity curves and trade logs."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RF_ANNUAL = float(__import__("os").environ.get("METRICS_RF", "0.03"))  # avg US risk-free over the windows


def series_metrics(dates, equity, tasi):
    eq = pd.Series(equity, index=pd.DatetimeIndex(dates))
    ret = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1.0
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0 if years > 0 else 0.0
    vol = ret.std() * math.sqrt(TRADING_DAYS)
    rf_d = RF_ANNUAL / TRADING_DAYS
    sharpe = ((ret - rf_d).mean() / ret.std()) * math.sqrt(TRADING_DAYS) if ret.std() > 0 else 0.0
    downside = ret[ret < rf_d]
    sortino = (((ret - rf_d).mean()) / downside.std()) * math.sqrt(TRADING_DAYS) if len(downside) > 1 and downside.std() > 0 else 0.0

    peak = eq.cummax()
    dd = eq / peak - 1.0
    mdd = dd.min()
    trough_i = dd.idxmin()
    peak_i = eq.loc[:trough_i].idxmax()
    rec = dd.loc[trough_i:]
    recovered = rec[rec >= -1e-9]
    recovery = str(recovered.index[0].date()) if len(recovered) else None
    # longest underwater stretch in sessions
    uw = (dd < -1e-9).astype(int)
    longest = cur = 0
    for v in uw:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)

    tasi_s = pd.Series(tasi, index=eq.index)
    tret = tasi_s.pct_change().dropna()
    common = ret.index.intersection(tret.index)
    r, b = ret.loc[common], tret.loc[common]
    if len(common) > 10 and b.var() > 0:
        beta = float(np.cov(r, b)[0, 1] / b.var())
        alpha_d = float(r.mean() - beta * b.mean())
        alpha_ann = (1 + alpha_d) ** TRADING_DAYS - 1
        corr = float(np.corrcoef(r, b)[0, 1])
    else:
        beta = alpha_ann = corr = 0.0

    monthly = eq.resample("ME").last().pct_change().dropna()
    m_first = eq.resample("ME").last()
    if len(m_first) > 0:
        first_m = m_first.index[0]
        monthly.loc[first_m] = m_first.iloc[0] / eq.iloc[0] - 1.0
        monthly = monthly.sort_index()

    best_day_i = ret.idxmax() if len(ret) else None
    worst_day_i = ret.idxmin() if len(ret) else None

    return {
        "final_equity": round(float(eq.iloc[-1]), 2),
        "total_return": round(float(total), 4),
        "cagr": round(float(cagr), 4),
        "ann_vol": round(float(vol), 4),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3),
        "max_drawdown": round(float(mdd), 4),
        "mdd_peak": str(peak_i.date()),
        "mdd_trough": str(trough_i.date()),
        "mdd_recovery": recovery,
        "longest_underwater_sessions": int(longest),
        "calmar": round(float(cagr / abs(mdd)), 3) if mdd < 0 else None,
        "beta_tasi": round(beta, 3),
        "alpha_annual": round(float(alpha_ann), 4),
        "corr_tasi": round(corr, 3),
        "var95_daily": round(float(ret.quantile(0.05)), 4) if len(ret) else 0.0,
        "skew": round(float(ret.skew()), 3) if len(ret) > 2 else 0.0,
        "best_day": {"date": str(best_day_i.date()), "ret": round(float(ret.max()), 4)} if best_day_i is not None else None,
        "worst_day": {"date": str(worst_day_i.date()), "ret": round(float(ret.min()), 4)} if worst_day_i is not None else None,
        "monthly_returns": {str(k.date())[:7]: round(float(v), 4) for k, v in monthly.items()},
        "positive_months_pct": round(float((monthly > 0).mean()), 3) if len(monthly) else 0.0,
    }


def trade_metrics(trades, equity, dates, names):
    sells = [t for t in trades if t["side"] == "sell" and "realized_pnl" in t]
    buys = [t for t in trades if t["side"] == "buy"]
    wins = [t for t in sells if t["realized_pnl"] > 0]
    losses = [t for t in sells if t["realized_pnl"] <= 0]
    gross_win = sum(t["realized_pnl"] for t in wins)
    gross_loss = -sum(t["realized_pnl"] for t in losses)
    traded_value = sum(t["value"] for t in trades)
    avg_eq = float(np.mean(equity)) if len(equity) else 1.0
    years = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25

    per_code = {}
    for t in trades:
        per_code.setdefault(t["code"], {"n": 0, "value": 0.0, "realized": 0.0})
        per_code[t["code"]]["n"] += 1
        per_code[t["code"]]["value"] += t["value"]
        if t["side"] == "sell":
            per_code[t["code"]]["realized"] += t.get("realized_pnl", 0.0)
    fav = max(per_code.items(), key=lambda kv: kv[1]["n"]) if per_code else None
    best_name = max(per_code.items(), key=lambda kv: kv[1]["realized"]) if per_code else None
    worst_name = min(per_code.items(), key=lambda kv: kv[1]["realized"]) if per_code else None

    best_trade = max(sells, key=lambda t: t["realized_pnl"]) if sells else None
    worst_trade = min(sells, key=lambda t: t["realized_pnl"]) if sells else None

    # longest completed hold
    longest_hold = None
    for t in sells:
        if t.get("held_since"):
            d = (pd.Timestamp(t["date"]) - pd.Timestamp(t["held_since"])).days
            if longest_hold is None or d > longest_hold["days"]:
                longest_hold = {"code": t["code"], "name": names.get(t["code"], t["code"]),
                                "days": d, "sold": t["date"], "bought": t["held_since"]}

    return {
        "n_trades": len(trades),
        "n_buys": len(buys),
        "n_sells": len(sells),
        "win_rate": round(len(wins) / len(sells), 3) if sells else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "realized_pnl": round(gross_win - gross_loss, 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "turnover_annual": round(traded_value / avg_eq / years, 2) if years > 0 else None,
        "favorite_stock": {"code": fav[0], "name": names.get(fav[0], fav[0]), "trades": fav[1]["n"]} if fav else None,
        "most_profitable_stock": {"code": best_name[0], "name": names.get(best_name[0], best_name[0]),
                                  "realized": round(best_name[1]["realized"], 2)} if best_name else None,
        "most_painful_stock": {"code": worst_name[0], "name": names.get(worst_name[0], worst_name[0]),
                               "realized": round(worst_name[1]["realized"], 2)} if worst_name else None,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "longest_hold": longest_hold,
    }
