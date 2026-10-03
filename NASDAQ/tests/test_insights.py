"""The insights step (docs/08 §6) on a synthetic market: exit levels exactly
as the frozen strategy places them, the four sub-scores, and prices."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import insights


def frame(days, close, atr_pct=0.03, turnover=50e6, sma_lift=0.9, d52=-0.02):
    close = np.asarray(close, dtype=float)
    df = pd.DataFrame(index=pd.DatetimeIndex(days, name="Date"))
    df["Close"] = close
    df["AdjClose"] = close
    df["atr14"] = close * atr_pct
    df["sma50"] = close * sma_lift
    df["sma100"] = close * sma_lift * 0.95
    df["sma200"] = close * sma_lift * 0.90
    df["turnover_sar"] = turnover
    df["ret_3m"], df["ret_6m"], df["ret_12m"] = 0.3, 0.5, 0.8
    df["vol_21"] = 0.4
    df["rs_bench_3m"] = 0.1
    df["dist_52w_high"] = d52
    return df


@pytest.fixture(scope="module")
def mod():
    return insights.load_strategy_module()


@pytest.fixture
def market():
    days = pd.bdate_range("2026-08-03", "2026-09-25")
    n = len(days)
    rising = np.linspace(100, 140, n)          # +40%: the trailing stop is armed
    flat = np.full(n, 50.0)
    return days, {"AAA": frame(days, rising), "BBB": frame(days, flat, d52=-0.25, sma_lift=1.2),
                  "IXIC": frame(days, np.linspace(1000, 1050, n))}


def twin_for(days):
    fill = days[10].date().isoformat()
    return {"agent": "trend", "live_start": days[0].date().isoformat(), "asof": days[-1].date().isoformat(),
            "params": {"STOP_ATR": 3.0, "TRAIL_ATR": 5.0, "TIME_STOP": 35.0, "RANK_BUFFER": 2.0},
            "positions": {"AAA": {"shares": 10, "price": 140.0, "avg_cost": 104.0},
                          "BBB": {"shares": 20, "price": 50.0, "avg_cost": 55.0}},
            "trades": [{"date": fill, "code": "AAA", "side": "buy", "shares": 10, "price": 104.0},
                       {"date": fill, "code": "BBB", "side": "buy", "shares": 20, "price": 55.0}],
            "journal": [{"date": fill, "mood": "trending", "sentiment": 0.4}]}


def test_exit_levels_follow_the_strategy(market, mod):
    days, frames = market
    doc = insights.build(days[-1].date().isoformat(), twin_for(days), frames, {"status": "pass", "checks": {}}, mod=mod)
    a = doc["positions"]["AAA"]
    dec = frames["AAA"].iloc[9]                         # the day before the fill
    assert a["initial_stop"] == pytest.approx(dec["AdjClose"] - 3.0 * dec["atr14"], abs=1e-3)
    assert a["trailing_stop"] == pytest.approx(140.0 - 5.0 * 140.0 * 0.03, abs=1e-3)
    assert a["nearest_exit"]["kind"] in ("trailing", "sma200")
    assert a["held_sessions"] == len(days) - 10
    assert a["rank"] is not None and a["rank_cut"] == 30
    assert a["sma_stack"] == "above SMA 50, 100 and 200"


def test_untriggered_trail_and_weak_signal(market, mod):
    days, frames = market
    doc = insights.build(days[-1].date().isoformat(), twin_for(days), frames, {"status": "pass", "checks": {}}, mod=mod)
    b = doc["positions"]["BBB"]
    assert b["trailing_stop"] is None                   # never 10% above entry
    assert b["sma_stack"] == "below SMA 50, 100 and 200"
    assert b["signal"] < doc["positions"]["AAA"]["signal"]


def test_scores_are_bounded_and_weighted(market, mod):
    days, frames = market
    doc = insights.build(days[-1].date().isoformat(), twin_for(days), frames, None, mod=mod)
    for p in doc["positions"].values():
        for k in ("signal", "risk_room", "regime", "data", "at_entry", "overall"):
            assert 0 <= p[k] <= 100
        assert p["overall"] == round(0.4 * p["signal"] + 0.3 * p["risk_room"] + 0.2 * p["regime"] + 0.1 * p["data"])
    assert doc["note"] == "model conviction, not a forecast"


def test_data_score_follows_the_gate(market, mod):
    assert insights.data_score({"status": "trip"}, "AAA") == (15, None)
    gate = {"status": "pass", "checks": {"cross_source": {"agreed": ["AAA"], "disagreements": [{"code": "BBB"}]}}}
    assert insights.data_score(gate, "AAA") == (100, "agree")
    assert insights.data_score(gate, "BBB") == (20, "disagree")
    assert insights.data_score(gate, "CCC") == (70, "unavailable")


def test_prices_are_written_for_the_chart(market, mod):
    days, frames = market
    doc = insights.build(days[-1].date().isoformat(), twin_for(days), frames, None, mod=mod)
    assert doc["prices"]["AAA"][-1] == [days[-1].date().isoformat(), 140.0]
    assert len(doc["prices"]["AAA"]) == len(days)
