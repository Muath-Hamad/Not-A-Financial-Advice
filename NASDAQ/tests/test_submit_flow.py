"""End-to-end nights through the submit step, Cycle B and the dead-man check,
against a scratch ledger and a fake broker (no network, no real keys)."""

from __future__ import annotations

import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

import pytest

import calendar_util
import config
import cycle_b
import cycle_submit
import deadman
from conftest import ASOF, FakeBroker, write_json

ET = ZoneInfo("America/New_York")
EVENING = dt.datetime(2026, 9, 28, 19, 15, tzinfo=ET)


@pytest.fixture
def night(monkeypatch, ledger, controls_dir, alerts):
    """Wire cycle_submit to the scratch ledger, controls and clock."""
    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(cycle_submit, "LIVE", controls_dir)
    monkeypatch.setattr(cycle_submit, "alert", alerts)
    monkeypatch.setattr(cycle_submit, "step_summary", lambda md: None)
    monkeypatch.setattr(calendar_util, "now_et", lambda: EVENING)
    monkeypatch.setenv("LIVE_MODE", "paper")
    monkeypatch.delenv("APPROVAL_MODE", raising=False)

    def run(broker, *argv):
        monkeypatch.setattr(cycle_submit, "get_broker", lambda: broker)
        monkeypatch.setattr(sys, "argv", ["cycle_submit.py", *argv])
        assert cycle_submit.main() == 0
        path = ledger / "cycles" / f"{ASOF}-S.json"
        return json.loads(path.read_text()) if path.exists() else None
    return run


def account_like_twin(**kw):
    return FakeBroker(cash=10_000.0, equity=100_000.0,
                      positions={"AAA": 100, "BBB": 200}, **kw)


def test_a_normal_paper_night(night, alerts):
    broker = account_like_twin()
    rec = night(broker)
    assert rec["status"] == "submitted"
    assert [(o["symbol"], o["side"], o["qty"]) for o in broker.sent] == \
        [("AAA", "sell", 100), ("CCC", "buy", 59)]
    assert rec["positions_before"] == {"AAA": 100, "BBB": 200}
    assert all(s["broker_id"] for s in rec["submissions"])
    assert [s["code"] for s in rec["plan"]["skipped"]] == ["DDD"]   # guardrail-blocked
    assert alerts.levels() == []


def test_the_night_is_sent_once(night):
    broker = account_like_twin()
    night(broker)
    night(broker)
    assert len(broker.sent) == 2


def test_outside_the_window_nothing_is_recorded(night, monkeypatch):
    monkeypatch.setattr(calendar_util, "now_et",
                        lambda: dt.datetime(2026, 9, 28, 17, 30, tzinfo=ET))
    broker = account_like_twin()
    assert night(broker) is None and broker.sent == []


def test_a_late_cycle_a_is_retried_not_skipped(night, ledger):
    (ledger / "cycles" / f"{ASOF}-A.json").unlink()
    broker = account_like_twin()
    assert night(broker) is None                  # nothing recorded yet...
    write_json(ledger / "cycles" / f"{ASOF}-A.json", {"cycle": "A", "asof": ASOF, "status": "ok"})
    assert night(broker)["status"] == "submitted"  # ...so the next slot sends


def test_kill_switch_holds_everything(night, controls_dir, alerts):
    write_json(controls_dir / "controls.json", {"kill": True, "excluded_symbols": []})
    broker = account_like_twin()
    rec = night(broker)
    assert rec["status"] == "held" and broker.sent == []
    assert alerts.levels() == ["P1"]


def test_reconciliation_halt_holds_until_cleared(night, ledger, alerts):
    write_json(ledger / "halt.json", {"halted": True, "since": "2026-09-25", "reason": "break"})
    broker = account_like_twin()
    rec = night(broker)
    assert rec["status"] == "held" and broker.sent == []
    assert "reconciliation halt" in rec["holds"][0]


def test_approval_mode_waits_for_a_manual_release(night, monkeypatch, alerts):
    monkeypatch.setenv("APPROVAL_MODE", "true")
    broker = account_like_twin()
    assert night(broker)["status"] == "held" and broker.sent == []
    assert alerts.levels() == ["P2"]
    assert night(broker)["status"] == "held"               # later slots keep holding
    assert night(broker, "--approved")["status"] == "submitted"
    assert len(broker.sent) == 2


def test_a_resent_order_is_resumed_not_duplicated(night):
    from broker import client_order_id
    coid = client_order_id(ASOF, {"code": "CCC", "side": "buy", "sar": 6_000.0})
    broker = account_like_twin(duplicate={"CCC"},
                               orders={coid: {"id": "alp-earlier", "status": "accepted"}})
    rec = night(broker)
    ccc = next(s for s in rec["submissions"] if s["code"] == "CCC")
    assert ccc["resumed"] and ccc["broker_id"] == "alp-earlier"
    assert rec["status"] == "submitted"


def test_a_rejected_order_is_a_p1(night, alerts):
    broker = account_like_twin(reject={"CCC": (403, '{"message":"insufficient buying power"}')})
    rec = night(broker)
    assert rec["status"] == "partial"
    assert [f["code"] for f in rec["failures"]] == ["CCC"]
    assert "P1" in alerts.levels()


def test_an_account_that_is_not_the_twins_book_is_held(night, alerts):
    broker = FakeBroker(cash=100_000.0, equity=100_000.0, positions={})  # never reset LIVE_START
    rec = night(broker)
    assert rec["status"] == "held" and broker.sent == []
    assert "LIVE_START" in rec["holds"][0]


def test_excluded_holding_is_force_exited_at_submit(night, controls_dir):
    write_json(controls_dir / "controls.json", {"kill": False, "excluded_symbols": ["BBB"]})
    broker = account_like_twin()
    rec = night(broker)
    sent = {(o["symbol"], o["side"]): o["qty"] for o in broker.sent}
    assert sent[("BBB", "sell")] == 200
    assert rec["status"] == "submitted"


def test_ghost_mode_rehearses_against_the_twin(night, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "ghost")
    import broker as broker_mod
    rec = night(broker_mod.GhostBroker())
    assert rec["status"] == "ghost_recorded"
    assert rec["positions_before"] == {"AAA": 100, "BBB": 200}
    assert [s["code"] for s in rec["submissions"]] == ["AAA", "CCC"]


# ---- Cycle B: trace fills, reconcile share for share -----------------------------

@pytest.fixture
def morning(monkeypatch, alerts):
    monkeypatch.setattr(cycle_b, "alert", alerts)
    monkeypatch.setattr(cycle_b, "fetch_opens", lambda codes, day: {c: None for c in codes})

    def run(broker, ledger):
        record = {"opens": {"AAA": 50.0, "CCC": 100.0, "BBB": 425.0}}
        cycle_b.reconcile_paper(broker, ledger, ASOF, "2026-09-29", record)
        return record
    return run


def fill_all(broker):
    for o in broker.orders.values():
        o.update(status="filled", filled_qty=str(next(
            s["qty"] for s in broker.sent if s["coid"] == o["client_order_id"])),
            filled_avg_price="100.05")


def test_clean_fills_reconcile(night, morning, ledger, alerts):
    broker = account_like_twin()
    night(broker)
    fill_all(broker)
    broker._positions = {"BBB": 200, "CCC": 59}
    rec = morning(broker, ledger)
    assert rec["reconcile"]["status"] == "ok"
    assert not (ledger / "halt.json").exists()
    assert rec["missed"] == []


def test_an_unexplained_position_halts_the_submit_step(night, morning, ledger, alerts):
    broker = account_like_twin()
    night(broker)
    fill_all(broker)
    broker._positions = {"BBB": 200, "CCC": 59, "ZZZ": 5}   # nobody ordered ZZZ
    rec = morning(broker, ledger)
    assert rec["reconcile"]["status"] == "break"
    halt = json.loads((ledger / "halt.json").read_text())
    assert halt["halted"] and halt["diffs"][0]["symbol"] == "ZZZ"
    assert "P1" in alerts.levels()
    # and the submit step holds from then on (replayed here on the same session)
    (ledger / "cycles" / f"{ASOF}-S.json").unlink()
    rec = night(broker)
    assert rec["status"] == "held" and any("reconciliation halt" in h for h in rec["holds"])


def test_unfilled_orders_are_reported_and_reconcile(night, morning, ledger, alerts):
    broker = account_like_twin()
    night(broker)
    for o in broker.orders.values():
        o.update(status="canceled", filled_qty="0")
    rec = morning(broker, ledger)        # positions unchanged: AAA 100, BBB 200
    assert rec["reconcile"]["status"] == "ok"
    assert {m["symbol"] for m in rec["missed"]} == {"AAA", "CCC"}
    assert alerts.levels() == ["P2"]


def test_no_account_snapshot_means_no_false_break(morning, ledger, alerts):
    write_json(ledger / "cycles" / f"{ASOF}-S.json",
               {"cycle": "S", "asof": ASOF, "status": "broker_unreachable"})
    rec = morning(account_like_twin(), ledger)
    assert rec["reconcile"]["status"] == "no_baseline"
    assert not (ledger / "halt.json").exists()


def test_orders_never_submitted_is_a_p1(morning, ledger, alerts):
    rec = morning(account_like_twin(), ledger)
    assert rec["reconcile"]["status"] == "no_submission_record"
    assert alerts.levels() == ["P1"]


# ---- the submit dead-man ----------------------------------------------------------

@pytest.fixture
def deadman_env(monkeypatch, ledger, alerts):
    monkeypatch.setattr(config, "LEDGER", ledger)
    monkeypatch.setattr(deadman, "alert", alerts)
    monkeypatch.setenv("LIVE_MODE", "paper")
    return ledger


def test_deadman_fires_when_orders_were_never_sent(deadman_env, alerts):
    deadman.check_submit(ASOF, 21)
    assert alerts.levels() == ["P1"]


def test_deadman_quiet_before_deadline_and_after_a_submit(deadman_env, alerts):
    deadman.check_submit(ASOF, 20)
    write_json(deadman_env / "cycles" / f"{ASOF}-S.json", {"status": "submitted"})
    deadman.check_submit(ASOF, 22)
    assert alerts == []


def test_deadman_not_applicable_in_ghost_mode(deadman_env, alerts, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "ghost")
    deadman.check_submit(ASOF, 23)
    assert alerts == []


def test_a_portfolio_guardrail_holds_until_a_manual_release(night, ledger, alerts):
    write_json(ledger / "cycles" / f"{ASOF}-A.json", {
        "cycle": "A", "asof": ASOF, "status": "ok",
        "guardrails": {"violations": [{"rule": "max_daily_turnover", "code": None,
                                       "side": None, "detail": "81.0% > 75%"}]}})
    broker = account_like_twin()
    rec = night(broker)
    assert rec["status"] == "held" and broker.sent == []
    assert alerts.levels() == ["P1"] and "manual run" in alerts[0][2]
    rec = night(broker, "--approved")
    assert rec["status"] == "submitted" and rec["released_by_manual_run"]


def test_a_manual_run_cannot_release_a_hard_hold(night, controls_dir):
    write_json(controls_dir / "controls.json", {"kill": True, "excluded_symbols": []})
    broker = account_like_twin()
    night(broker)
    assert night(broker, "--approved")["status"] == "held" and broker.sent == []
