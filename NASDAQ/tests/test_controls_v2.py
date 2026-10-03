"""controls.json v2 (docs/08 §7.2): schema, locks, the submit-time pause,
manual orders, flatten / cancel commands and the adapt() pause."""

from __future__ import annotations

import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

import pytest

import calendar_util
import config
import control_cmd
import controls_schema as cs
import cycle_submit
from broker import client_order_id
from conftest import ASOF, FakeBroker, write_json
from execution import manual_order_id, plan_submissions
from guardrails import check_orders

ET = ZoneInfo("America/New_York")
EVENING = dt.datetime(2026, 9, 28, 19, 15, tzinfo=ET)


def manual(mid="m1", symbol="AAA", side="sell", qty=None, fraction=None, expires=ASOF, **kw):
    return {"id": mid, "symbol": symbol, "side": side, "qty": qty, "fraction": fraction,
            "reason": "reduce concentration ahead of earnings", "created_by": "owner@console",
            "created": ASOF, "expires": expires, **kw}


def entry(code, side, qty=None, close=None, **fields):
    od = {"code": code, "side": side, **fields}
    return {**od, "client_order_id": client_order_id(ASOF, od), "ref_close": close,
            "share_preview": {"symbol": code, "side": side, "qty": qty} if qty else None, "blocked": []}


# ---- schema ------------------------------------------------------------------

def test_missing_keys_mean_off():
    c = cs.normalize({"kill": False, "excluded_symbols": ["PEP"]})
    assert c["locked_symbols"] == [] and c["manual_orders"] == []
    assert c["pause_adapt"] is False and c["allow_manual_buys"] is False and c["version"] == 2
    assert cs.validate(c) == []


def test_the_committed_controls_file_is_valid():
    assert cs.validate(cs.load(config.LIVE / "controls.json")) == []


@pytest.mark.parametrize("patch, needle", [
    ({"kill": "yes"}, "kill must be"),
    ({"gross_cap": 1.5}, "gross_cap"),
    ({"locked_symbols": ["aaa"]}, "locked_symbols"),
    ({"locked_symbols": ["PEP"], "excluded_symbols": ["PEP"]}, "both excluded and locked"),
    ({"manual_orders": [manual(qty=None, fraction=None)]}, "exactly one of qty or fraction"),
    ({"manual_orders": [manual(side="buy", qty=5)]}, "manual buys are off"),
    ({"manual_orders": [manual(qty=5), manual(qty=3)]}, "duplicate id"),
    ({"manual_orders": [manual(qty=5, reason="short")]}, "reason"),
    ({"pause_adapt_since": "next week"}, "pause_adapt_since"),
])
def test_validation_catches(patch, needle):
    errs = cs.validate(cs.normalize(patch))
    assert any(needle in e for e in errs), errs


def test_active_manual_orders_respect_creation_and_expiry():
    c = cs.normalize({"manual_orders": [manual("old", expires="2026-09-25", qty=1),
                                        manual("now", qty=1),
                                        manual("later", qty=1, created="2026-09-29", expires="2026-09-29")]})
    assert [m["id"] for m in cs.active_manual_orders(c, ASOF)] == ["now"]


# ---- plan_submissions ----------------------------------------------------------

def test_locked_names_are_left_alone():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", all=True), entry("CCC", "buy", qty=10, close=100.0)],
                            held={"AAA": 40}, closes={"AAA": 50.0, "CCC": 100.0}, cash=5_000.0,
                            equity=100_000.0, excluded=set(), slippage=0.0005, locked={"AAA", "CCC"})
    assert plan["submit"] == []
    assert {s["reason"] for s in plan["skipped"]} == {"locked"}


def test_exclusion_wins_over_a_lock():
    plan = plan_submissions(ASOF, [], held={"BAD": 7}, closes={"BAD": 10.0}, cash=0.0,
                            equity=100_000.0, excluded={"BAD"}, slippage=0.0005, locked={"BAD"})
    assert [(o["code"], o["qty"], o["forced"]) for o in plan["submit"]] == [("BAD", 7, True)]


def test_pause_at_submit_blocks_buys_but_not_sells():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", all=True), entry("CCC", "buy", qty=10, close=100.0)],
                            held={"AAA": 40}, closes={"AAA": 50.0, "CCC": 100.0}, cash=5_000.0,
                            equity=100_000.0, excluded=set(), slippage=0.0005, pause_entries=True)
    assert [(o["code"], o["side"]) for o in plan["submit"]] == [("AAA", "sell")]
    assert plan["skipped"][0]["reason"] == "pause_entries"


def test_manual_sell_is_capped_at_the_account_holding_and_tagged():
    m = manual(qty=500)
    plan = plan_submissions(ASOF, [], held={"AAA": 40}, closes={"AAA": 50.0}, cash=0.0,
                            equity=100_000.0, excluded=set(), slippage=0.0005, manual=[m])
    o = plan["submit"][0]
    assert (o["code"], o["side"], o["qty"], o["manual_id"]) == ("AAA", "sell", 40, "m1")
    assert o["client_order_id"] == manual_order_id(ASOF, m)


def test_manual_fraction_and_not_held():
    plan = plan_submissions(ASOF, [], held={"AAA": 41}, closes={"AAA": 50.0}, cash=0.0, equity=100_000.0,
                            excluded=set(), slippage=0.0005,
                            manual=[manual(fraction=0.5), manual("m2", symbol="ZZZ", qty=3)])
    assert [(o["code"], o["qty"]) for o in plan["submit"]] == [("AAA", 20)]
    assert plan["skipped"][0]["reason"] == "not held at the broker"


def test_manual_sell_does_not_double_an_agent_sell():
    plan = plan_submissions(ASOF, [entry("AAA", "sell", all=True)], held={"AAA": 40}, closes={"AAA": 50.0},
                            cash=0.0, equity=100_000.0, excluded=set(), slippage=0.0005, manual=[manual(qty=5)])
    assert len(plan["submit"]) == 1 and plan["skipped"][0]["manual_id"] == "m1"


def test_manual_buys_need_the_switch_and_pass_the_cash_check():
    m = manual("b1", symbol="CCC", side="buy", qty=80)
    off = plan_submissions(ASOF, [], held={}, closes={"CCC": 100.0}, cash=5_000.0, equity=100_000.0,
                           excluded=set(), slippage=0.0005, manual=[m])
    assert off["submit"] == [] and off["skipped"][0]["reason"] == "manual buys are off"
    on = plan_submissions(ASOF, [], held={}, closes={"CCC": 100.0}, cash=5_000.0, equity=100_000.0,
                          excluded=set(), slippage=0.0005, manual=[m], allow_manual_buys=True)
    assert on["submit"][0]["qty"] < 80 and on["adjusted"][0]["reason"] == "cash after tonight's sells"


def test_guardrails_flag_agent_orders_on_locked_names():
    twin = {"equity_final": 100_000.0, "positions": {"AAA": {"value": 5_000.0}}}
    rails = check_orders([{"code": "AAA", "side": "sell", "all": True}], twin, {}, {"AAA"},
                         {"locked_symbols": ["AAA"], "excluded_symbols": []})
    assert [v["rule"] for v in rails["violations"]] == ["locked"]


# ---- the submit step reads controls at submit time -------------------------------

@pytest.fixture
def night(monkeypatch, ledger, controls_dir, alerts):
    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(cycle_submit, "LIVE", controls_dir)
    monkeypatch.setattr(cycle_submit, "alert", alerts)
    monkeypatch.setattr(cycle_submit, "step_summary", lambda md: None)
    monkeypatch.setattr(calendar_util, "now_et", lambda: EVENING)
    monkeypatch.setenv("LIVE_MODE", "paper")
    monkeypatch.delenv("APPROVAL_MODE", raising=False)

    def run(broker, controls):
        write_json(controls_dir / "controls.json", controls)
        monkeypatch.setattr(cycle_submit, "get_broker", lambda: broker)
        monkeypatch.setattr(sys, "argv", ["cycle_submit.py"])
        assert cycle_submit.main() == 0
        return json.loads((ledger / "cycles" / f"{ASOF}-S.json").read_text())
    return run


def test_a_pause_committed_after_cycle_a_stops_tonights_buys(night):
    broker = FakeBroker(cash=10_000.0, positions={"AAA": 100, "BBB": 200})
    rec = night(broker, {"pause_entries": True})
    assert [(o["symbol"], o["side"]) for o in broker.sent] == [("AAA", "sell")]
    assert rec["controls"]["pause_entries"] is True


def test_lock_and_manual_trim_reach_the_broker(night):
    broker = FakeBroker(cash=10_000.0, positions={"AAA": 100, "BBB": 200})
    rec = night(broker, {"locked_symbols": ["AAA"], "manual_orders": [manual(symbol="BBB", qty=50)]})
    assert sorted((o["symbol"], o["side"], o["qty"]) for o in broker.sent) == [("BBB", "sell", 50), ("CCC", "buy", 59)]
    assert rec["controls"]["manual_orders"] == ["m1"]
    assert any(s["reason"] == "locked" for s in rec["plan"]["skipped"])


# ---- immediate commands -------------------------------------------------------------

class CmdBroker(FakeBroker):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.canceled = False

    def cancel_all(self):
        self.canceled = True
        return {"status": "ok", "canceled": [{"id": "o1"}]}

    def flatten(self, day):
        return {"status": "ok", "orders": [{"symbol": s, "qty": q} for s, q in self._positions.items()]}


def test_cancel_all_writes_a_command_record(tmp_path):
    b = CmdBroker(positions={"AAA": 5})
    rec = control_cmd.run("cancel_all", "data gate failing, stop now", "owner@console", "01JTEST", tmp_path, broker=b)
    assert b.canceled and rec["status"] == "ok" and "flatten" not in rec
    saved = json.loads(next((tmp_path / "commands").glob("*-cancel_all.json")).read_text())
    assert saved["console_action_id"] == "01JTEST" and saved["mode"] == "paper"


def test_flatten_cancels_then_sells_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_util, "latest_completed_session", lambda *a: ASOF)
    b = CmdBroker(positions={"AAA": 5, "BBB": 7})
    rec = control_cmd.run("flatten", "evaluation ended early", "owner@console", None, tmp_path, broker=b)
    assert b.canceled and [o["symbol"] for o in rec["flatten"]["orders"]] == ["AAA", "BBB"]


def test_command_failures_are_recorded_not_raised(tmp_path):
    class Down(CmdBroker):
        def cancel_all(self):
            raise RuntimeError("timeout")
    rec = control_cmd.run("cancel_all", "broker anomaly seen", "owner@console", None, tmp_path, broker=Down())
    assert rec["status"] == "failed" and "timeout" in rec["error"]


def test_a_reason_is_required(tmp_path):
    with pytest.raises(ValueError):
        control_cmd.run("cancel_all", "short", "owner@console", None, tmp_path, broker=CmdBroker())


# ---- adapt() pause ---------------------------------------------------------------------

def test_engine_skips_adapt_from_the_pause_date(monkeypatch):
    import importlib
    sys.path.insert(0, str(config.PKG / "sim"))
    monkeypatch.setenv("SIM_ADAPT_PAUSE_FROM", "2026-10-01")
    import engine
    importlib.reload(engine)
    try:
        assert engine.ADAPT_PAUSE_FROM == "2026-10-01"
    finally:
        monkeypatch.delenv("SIM_ADAPT_PAUSE_FROM")
        importlib.reload(engine)
    assert engine.ADAPT_PAUSE_FROM == ""
