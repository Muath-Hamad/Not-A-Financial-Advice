"""The console's payload builders over a synthetic ledger (docs/08 §4–§6,
§10). Only what the ledger says; nothing estimated."""

from __future__ import annotations

import datetime as dt
import json

from nafa_console import payloads as P
from nafa_console.ledger import load_snapshot

# Thu 1 Oct 2026, 18:00 ET — after Cycle A should have valued Tue 29 and Wed 30 Sep.
NOW = dt.datetime(2026, 10, 1, 18, 0, tzinfo=P.cal.ET)



def ctx(settings, indexer=None, now=NOW):
    return P.Ctx(load_snapshot(settings), settings, now, indexer or {"last": {"ok": 1}, "last_ok": {"at_utc": "2026-10-01T21:58:00+00:00"}})


def test_system_reports_stale_failing_cycle_a(settings):
    s = P.system(ctx(settings))
    assert s["env"] == "ghost"
    assert s["health"] == "stale"
    assert s["trading"] == "running"
    f = s["facts"]
    assert f["model"]["asof"] == "2026-09-25"
    assert f["model"]["builtAt"] == "17:05 ET"
    assert f["failing"] == {"count": 2, "from": "2026-09-28", "to": "2026-09-29",
                            "reason": "Data gate tripped: coverage at asof 0.6% < 95%",
                            "checks": "fetch ok 97.0% · cross-source 1 compared, 39 unavailable"}
    assert f["model"]["sessionsBehind"] == 4  # 28, 29, 30 Sep and 1 Oct
    assert f["nextOpen"] == "2026-10-02"
    assert f["screen"] == {"last": "2026-10-01", "next": "2027-01-01"}


def test_health_is_loaded_when_the_last_cycle_a_passed(settings):
    for d in ("2026-09-28", "2026-09-29"):
        (settings.ledger_dir / "cycles" / f"{d}-A.json").unlink()
    c = ctx(settings, now=dt.datetime(2026, 9, 25, 18, 30, tzinfo=P.cal.ET))
    assert c.failing is None
    assert c.health == "loaded"


def test_kill_switch_and_halt_set_the_trading_state(settings):
    ctl = settings.pkg / "live" / "controls.json"
    data = json.loads(ctl.read_text())
    data["pause_entries"] = True
    ctl.write_text(json.dumps(data))
    assert P.system(ctx(settings))["trading"] == "paused"
    (settings.ledger_dir / "halt.json").write_text(json.dumps({"halted": True, "since": "2026-09-30", "reason": "break", "diffs": [{"symbol": "AAA", "expected": 120, "actual": 119, "diff": -1}]}))
    s = P.system(ctx(settings))
    assert s["trading"] == "halted"
    assert s["facts"]["halt"] == {"symbol": "AAA", "expected": 120, "actual": 119, "at": "2026-09-30"}
    data["kill"] = True
    ctl.write_text(json.dumps(data))
    assert P.system(ctx(settings))["trading"] == "stopped"


def test_positions_carry_ledger_facts_and_null_for_missing_insights(settings):
    pos = P.holdings(ctx(settings))["positions"]
    assert len(pos) == 1
    a = pos[0]
    assert a["symbol"] == "AAA" and a["name"] == "AAA Corp"
    assert a["shares"] == 120 and a["avgCost"] == 10.1716 and a["last"] == 12.0
    assert a["entryDate"] == "2026-09-14"
    assert a["heldSessions"] == 10  # 14 → 25 Sep inclusive
    assert a["entryReason"] == "rank 1 momentum, 2% off the 52w high, ATR 3.0% → 12% line"
    # ratios from the fresher 1 Oct re-screen, in percent
    assert (a["debtPct"], a["cashPct"], a["screenedOn"]) == (6.0, 4.0, "2026-10-01")
    assert a["review"]["keyword"] == "streaming entertainment platform"
    # not in the ledger yet → null, never estimated
    for k in ("confidence", "initialStop", "trailingStop", "atr", "rank", "dayPct", "account"):
        assert a[k] is None, k


def test_insights_file_fills_confidence_and_stops(settings):
    ins = settings.ledger_dir / "insights" / "2026-09-25.json"
    ins.parent.mkdir(parents=True)
    ins.write_text(json.dumps({"positions": {"AAA": {"signal": 80, "risk_room": 60, "regime": 50, "data": 90, "at_entry": 70, "atr": 0.4, "initial_stop": 8.97, "trailing_stop": 10.5}}}))
    a = P.holdings(ctx(settings))["positions"][0]
    assert a["confidence"] == {"signal": 80, "riskRoom": 60, "regime": 50, "data": 90, "atEntry": 70}
    assert (a["atr"], a["initialStop"], a["trailingStop"]) == (0.4, 8.97, 10.5)


def test_fifo_lots_for_the_open_holding(settings):
    assert P.lots(ctx(settings), "AAA") == [{"opened": "2026-09-14", "shares": 100, "cost": 10.005}, {"opened": "2026-09-23", "shares": 20, "cost": 11.0055}]


def test_history_derives_the_official_open_from_the_modelled_slippage(settings):
    h = P.history(ctx(settings))
    assert h["total"] == 4
    newest, sell = h["orders"][0], h["orders"][1]
    assert newest["symbol"] == "AAA" and newest["fillDate"] == "2026-09-23" and newest["decisionDate"] == "2026-09-22"
    assert abs(newest["officialOpen"] - 11.0) < 1e-9          # 11.0055 / 1.0005
    assert abs(sell["officialOpen"] - 36.0) < 1e-9            # 35.982 / 0.9995
    assert sell["decisionClose"] is None                      # the twin does not ledger it
    assert sell["heldDays"] == 6


def test_round_trips_back_out_the_entry_price(settings):
    t = P.round_trips(ctx(settings))["trips"]
    assert len(t) == 1
    assert t[0]["symbol"] == "BBB" and t[0]["exitReason"] == "stop"
    assert abs(t[0]["entryPrice"] - (35.982 + 201.9 / 50)) < 1e-9
    assert t[0]["confAtEntry"] is None


def test_an_expired_plan_is_not_shown_as_pending(settings):
    p = P.pending(ctx(settings))
    assert p["intents"] == []           # orders were for Mon 28 Sep's open, long gone
    assert p["nextOpen"] == "2026-10-02"


def test_pending_maps_the_orders_ledger(settings):
    c = ctx(settings, now=dt.datetime(2026, 9, 25, 18, 30, tzinfo=P.cal.ET))
    o = P.pending(c)["intents"][0]
    assert o["symbol"] == "CCC" and o["side"] == "BUY" and o["shares"] == 100
    assert o["amountLabel"] == "$2,500 → 100 sh"
    assert o["guardrail"] == "adv_cap" and o["estValue"] == 2500.0
    assert o["reason"] == "rank 3 momentum → 9% line"


def test_grade_follows_docs_08_section_5():
    assert P.grade(5, 4, False, False, 10) == "A"
    assert P.grade(22, 4, False, False, 10) == "B"     # under 10 pp headroom
    assert P.grade(28.5, 4, False, False, 10) == "C"   # under 3 pp
    assert P.grade(5, 4, True, False, 10) == "C"       # review-flagged
    assert P.grade(5, 4, False, False, 150) == "B"     # data 100–200 days old
    assert P.grade(31, 4, False, False, 10) == "F"     # fails the ratio
    assert P.grade(5, 4, False, True, 10) == "F"       # excluded
    assert P.grade(None, 4, False, False, 10) == "C"   # no figure


def test_compliance_explains_rescreen_reasons_from_the_fresh_screen(settings):
    c = P.compliance(ctx(settings))
    assert c["universeSize"] == 4 and c["reviewFlagged"] == 1 and c["excludedAfterRescreen"] == 1
    rows = {r["symbol"]: r for r in c["universe"]}
    assert rows["DDD"]["status"] == "Excluded" and rows["DDD"]["grade"] == "F"
    assert rows["CCC"]["grade"] == "C" and rows["BBB"]["grade"] == "B" and rows["AAA"]["status"] == "Under review"
    q4 = c["rescreens"][0]
    assert q4["out"] == [{"symbol": "DDD", "reason": "debt/mcap 31% >= 30%"}]
    assert q4["in"] == ["EEE"]
    assert c["rescreens"][-1]["out"][0]["symbol"] == "ZZZP"


def test_alerts_are_derived_and_keep_their_ids(settings):
    a1 = P.alerts(ctx(settings), {})["alerts"]
    titles = [a["title"] for a in a1]
    assert titles[0] == "Cycle A failed 2 sessions in a row — data gate tripped"
    assert "Model book 4 sessions behind" in titles
    assert any(t.startswith("AAA review-flagged") for t in titles)
    a2 = P.alerts(ctx(settings), {a1[0]["id"]: {"status": "acknowledged", "note": ""}})["alerts"]
    assert a2[0]["id"] == a1[0]["id"] and a2[0]["status"] == "acknowledged"


def test_health_grid_and_gate(settings):
    h = P.health(ctx(settings))
    assert len(h["sessions"]) == 14
    assert h["cycles"]["A"][-3:] == ["fail", "skip", "skip"] or h["cycles"]["A"][-2:] == ["fail", "skip"]
    assert h["gate"]["stalled"] == "Stalled — 2 failed sessions"
    assert h["dataGate"]["tripped"] == "Tripped 2 sessions"
    assert h["dataGate"]["checks"][2] == {"ok": False, "label": "Coverage at asof", "value": "0.6%", "min": "min 95%"}
    assert h["degraded"] is True


def test_overview_curve_and_phase(settings):
    o = P.overview(ctx(settings))
    assert [p["model"] for p in o["equityCurve"]] == [100000.0, 99800.0, 99500.0]
    assert all(p["account"] is None for p in o["equityCurve"])
    assert o["phase"]["title"] == "Phase 1 · Ghost" and o["phase"]["n"] == 1
    assert o["controls"]["excludedSymbols"] == ["DDD"] and o["controls"]["forcedExits"] == []


def test_roadmap_counts_days_to_each_decision(settings):
    r = P.roadmap(ctx(settings), open_p1=True)
    d1 = next(d for d in r["decisions"] if d["id"] == "D1")
    assert d1["daysLeft"] == 29  # 1 Oct → 30 Oct
    assert r["phases"][0]["gates"][0]["ok"] is False
    assert r["currentFailing"] is True
