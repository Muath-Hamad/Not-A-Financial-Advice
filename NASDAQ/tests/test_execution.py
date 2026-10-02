"""The pure execution rules: what reaches the broker, and what is a break."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import config
from broker import client_order_id
from execution import (broker_holdings, diff_positions, drift_vs_twin, expected_positions,
                       in_submit_window, plan_submissions)

ET = ZoneInfo("America/New_York")
ASOF = "2026-09-28"


def entry(code, side, qty=None, close=None, blocked=None, **fields):
    od = {"code": code, "side": side, **fields}
    return {**od, "client_order_id": client_order_id(ASOF, od), "ref_close": close,
            "share_preview": {"symbol": code, "side": side, "qty": qty} if qty else None,
            "blocked": blocked or []}


# ---- the on-open window ------------------------------------------------------

def test_submit_window_edges():
    at = lambda h, m: dt.datetime(2026, 9, 28, h, m, tzinfo=ET)  # noqa: E731
    assert not in_submit_window(at(17, 0))    # Cycle A decides; too early to send
    assert not in_submit_window(at(18, 59))
    assert in_submit_window(at(19, 0))
    assert in_submit_window(at(23, 59))
    assert in_submit_window(at(0, 0))
    assert in_submit_window(at(9, 27))
    assert not in_submit_window(at(9, 28))    # Alpaca's cutoff
    assert not in_submit_window(at(12, 0))


def test_broker_holdings_whole_shares_only():
    got = broker_holdings([{"symbol": "AAA", "qty": "100"}, {"symbol": "BBB", "qty": "0"},
                           {"symbol": "CCC", "qty": "2.5"}, {"symbol": "DDD", "qty": None}])
    assert got == {"AAA": 100, "CCC": 2}


# ---- plan_submissions ----------------------------------------------------------

def test_sells_are_sized_from_the_account_not_the_twin():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", all=True)], held={"AAA": 37},
                            closes={"AAA": 50.0}, cash=0.0, equity=100_000.0,
                            excluded=set(), slippage=0.0005)
    assert [(o["code"], o["qty"]) for o in plan["submit"]] == [("AAA", 37)]


def test_partial_sell_uses_the_fraction_of_account_shares():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", fraction=0.5)], held={"AAA": 81},
                            closes={"AAA": 50.0}, cash=0.0, equity=100_000.0,
                            excluded=set(), slippage=0.0005)
    assert plan["submit"][0]["qty"] == 40


def test_sell_of_a_name_the_account_does_not_hold_is_skipped():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", all=True)], held={},
                            closes={"AAA": 50.0}, cash=0.0, equity=100_000.0,
                            excluded=set(), slippage=0.0005)
    assert plan["submit"] == []
    assert plan["skipped"][0]["reason"] == "not held at the broker"


def test_blocked_entries_never_reach_the_broker():
    plan = plan_submissions(ASOF, [entry("DDD", "buy", qty=10, close=20.0, blocked=["adv_cap"])],
                            held={}, closes={"DDD": 20.0}, cash=50_000.0, equity=100_000.0,
                            excluded=set(), slippage=0.0005)
    assert plan["submit"] == []
    assert plan["skipped"][0]["reason"] == "blocked: adv_cap"


def test_excluded_holding_gets_a_forced_exit_even_without_a_ledger_sell():
    plan = plan_submissions(ASOF, [], held={"BAD": 12, "OK": 5}, closes={"BAD": 10.0},
                            cash=0.0, equity=100_000.0, excluded={"BAD"}, slippage=0.0005)
    assert [(o["code"], o["side"], o["qty"], o["forced"]) for o in plan["submit"]] == \
        [("BAD", "sell", 12, True)]
    # deterministic id: a re-run cannot double-send the forced exit
    again = plan_submissions(ASOF, [], held={"BAD": 12}, closes={"BAD": 10.0}, cash=0.0,
                             equity=100_000.0, excluded={"BAD"}, slippage=0.0005)
    assert again["submit"][0]["client_order_id"] == plan["submit"][0]["client_order_id"]


def test_forced_exit_is_not_duplicated_when_the_ledger_already_sells():
    plan = plan_submissions(ASOF, [entry("BAD", "sell", all=True, forced=True)],
                            held={"BAD": 12}, closes={"BAD": 10.0}, cash=0.0,
                            equity=100_000.0, excluded={"BAD"}, slippage=0.0005)
    assert len(plan["submit"]) == 1


def test_buys_fit_the_cash_that_tonight_sells_free():
    # 1,000 cash + 100 x 50 sold = ~6,000; the buffer keeps 0.2% of equity back
    entries = [entry("AAA", "sell", all=True),
               entry("CCC", "buy", qty=40, close=100.0),
               entry("EEE", "buy", qty=30, close=100.0)]
    plan = plan_submissions(ASOF, entries, held={"AAA": 100},
                            closes={"AAA": 50.0, "CCC": 100.0, "EEE": 100.0},
                            cash=1_000.0, equity=100_000.0, excluded=set(), slippage=0.0005)
    sent = {o["code"]: o["qty"] for o in plan["submit"]}
    assert sent["AAA"] == 100 and sent["CCC"] == 40
    # budget: 1,000 - 200 + 5,000 x 0.9995 = 5,797.5; CCC uses 4,002 -> 17 EEE shares fit
    assert sent["EEE"] == 17
    assert plan["adjusted"] == [{"code": "EEE", "from": 30, "to": 17,
                                 "reason": "cash after tonight's sells"}]
    spend = sum(q * 100.0 * 1.0005 for c, q in sent.items() if c != "AAA")
    assert spend <= 1_000.0 - config.CASH_BUFFER * 100_000.0 + 5_000.0 * 0.9995


def test_buy_dropped_when_no_cash_is_left():
    plan = plan_submissions(ASOF, [entry("CCC", "buy", qty=5, close=100.0)], held={},
                            closes={"CCC": 100.0}, cash=100.0, equity=10_000.0,
                            excluded=set(), slippage=0.0005)
    assert plan["submit"] == []
    assert plan["skipped"][0]["reason"] == "no cash left after earlier buys"


def test_buy_without_a_share_estimate_is_skipped():
    plan = plan_submissions(ASOF, [entry("CCC", "buy")], held={}, closes={},
                            cash=10_000.0, equity=10_000.0, excluded=set(), slippage=0.0005)
    assert plan["submit"] == []
    assert "no share estimate" in plan["skipped"][0]["reason"]


def test_sells_go_first():
    entries = [entry("CCC", "buy", qty=1, close=100.0), entry("AAA", "sell", all=True)]
    plan = plan_submissions(ASOF, entries, held={"AAA": 3}, closes={"AAA": 50.0, "CCC": 100.0},
                            cash=10_000.0, equity=10_000.0, excluded=set(), slippage=0.0005)
    assert [o["side"] for o in plan["submit"]] == ["sell", "buy"]


# ---- reconciliation ------------------------------------------------------------

def test_expected_positions_applies_partial_and_full_fills():
    before = {"AAA": 100, "BBB": 10}
    fills = [{"symbol": "AAA", "side": "sell", "filled_qty": 100},
             {"symbol": "CCC", "side": "buy", "filled_qty": "7"},
             {"symbol": "BBB", "side": "buy", "filled_qty": 0}]
    assert expected_positions(before, fills) == {"BBB": 10, "CCC": 7}


def test_diff_positions_reports_every_mismatch():
    assert diff_positions({"A": 1, "B": 2}, {"A": 1, "B": 2}) == []
    assert diff_positions({"A": 1}, {"A": 2, "Z": 5}) == [
        {"symbol": "A", "expected": 1, "actual": 2, "diff": 1},
        {"symbol": "Z", "expected": 0, "actual": 5, "diff": 5}]


# ---- twin vs account drift -------------------------------------------------------

def test_small_share_differences_are_tolerated():
    twin = {"AAA": {"shares": 100, "price": 50.0}}
    d = drift_vs_twin(twin, {"AAA": 98}, {"AAA": 50.0}, 100_000.0)
    assert d["breaches"] == [] and d["names"][0]["diff"] == -2


def test_large_differences_breach_and_count_toward_the_gap():
    twin = {"AAA": {"shares": 100, "price": 50.0}}
    d = drift_vs_twin(twin, {"AAA": 50, "ZZZ": 10}, {"AAA": 50.0, "ZZZ": 10.0}, 10_000.0)
    assert {b["symbol"] for b in d["breaches"]} == {"AAA", "ZZZ"}
    assert d["gap_share"] == round((50 * 50.0 + 10 * 10.0) / 10_000.0, 4)


def test_forced_exits_are_explained_not_breaches():
    twin = {"BAD": {"shares": 300, "price": 10.0}}
    d = drift_vs_twin(twin, {}, {"BAD": 10.0}, 10_000.0, explained={"BAD"})
    assert d["breaches"] == [] and d["gap_share"] == 0.0
    assert d["names"][0]["explained"]


def test_a_partial_sell_of_an_excluded_name_becomes_a_full_exit():
    plan = plan_submissions(ASOF, [entry("BAD", "sell", fraction=0.5)], held={"BAD": 40},
                            closes={"BAD": 10.0}, cash=0.0, equity=100_000.0,
                            excluded={"BAD"}, slippage=0.0005)
    assert [(o["code"], o["qty"], o["forced"]) for o in plan["submit"]] == [("BAD", 40, True)]
