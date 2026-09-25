"""Compliance guardrails stop buys, never sales (docs/07)."""

from __future__ import annotations

from guardrails import check_orders

TWIN = {"equity_final": 100_000.0,
        "positions": {"OLD": {"shares": 10, "value": 1_000.0}}}
UNIVERSE = {"OK", "OLD2"}  # OLD fell out of the screened universe


def rules(orders, controls=None):
    res = check_orders(orders, TWIN, {}, UNIVERSE, controls or {})
    return {(v["code"], v["side"], v["rule"]) for v in res["violations"]}


def test_buy_outside_the_universe_is_blocked():
    assert ("NEW", "buy", "whitelist") in rules([{"code": "NEW", "side": "buy", "sar": 100.0}])


def test_sale_of_a_name_outside_the_universe_is_allowed():
    assert rules([{"code": "OLD", "side": "sell", "all": True}]) == set()


def test_exclusion_blocks_buys_only():
    controls = {"excluded_symbols": ["OK", "OLD"]}
    got = rules([{"code": "OK", "side": "buy", "sar": 100.0},
                 {"code": "OLD", "side": "sell", "all": True}], controls)
    assert got == {("OK", "buy", "excluded")}


def test_pause_entries_blocks_buys_only():
    got = rules([{"code": "OK", "side": "buy", "sar": 100.0},
                 {"code": "OLD", "side": "sell", "all": True}], {"pause_entries": True})
    assert got == {("OK", "buy", "pause_entries")}


def test_sell_of_a_name_the_book_does_not_hold_is_flagged():
    assert ("NONE", "sell", "long_only") in rules([{"code": "NONE", "side": "sell", "all": True}])


def test_position_cap():
    got = rules([{"code": "OK", "side": "buy", "sar": 20_000.0}])
    assert ("OK", "buy", "max_pos_weight") in got
