"""The re-screen report carries a per-name screened_on (docs/08 §7.2)."""

from __future__ import annotations

import json
import sys

import config
import rescreen_report


def test_report_has_per_name_results(tmp_path, monkeypatch, alerts):
    pkg = tmp_path / "NASDAQ"
    (pkg / "data" / "rescreen").mkdir(parents=True)
    (pkg / "live").mkdir()
    u = lambda c, d, ok=True: {"code": c, "debt_ratio": d, "cash_ratio": 0.01, "pass": ok}  # noqa: E731
    (pkg / "data" / "universe_screened.json").write_text(json.dumps({"universe": [u("AAA", 0.1), u("BBB", 0.2)]}))
    (pkg / "data" / "rescreen" / "x.json").write_text(json.dumps({
        "universe": [u("AAA", 0.12)],
        "rejected_detail": [{**u("BBB", 0.31, False), "ratio_reasons": ["debt/mcap 31% >= 30%"]}]}))
    (pkg / "live" / "controls.json").write_text(json.dumps({"excluded_symbols": []}))
    monkeypatch.setattr(rescreen_report, "PKG", pkg)
    monkeypatch.setattr(rescreen_report, "LIVE", pkg / "live")
    monkeypatch.setattr(config, "LEDGER", tmp_path / "ledger")
    monkeypatch.setattr(rescreen_report, "alert", alerts)
    monkeypatch.setattr(rescreen_report, "step_summary", lambda md: None)
    monkeypatch.setattr(sys, "argv", ["rescreen_report.py", "--fresh", "data/rescreen/x.json"])
    assert rescreen_report.main() == 0
    rep = json.loads(next((tmp_path / "ledger" / "compliance").glob("*.json")).read_text())
    assert rep["names"]["AAA"]["debt_ratio"] == 0.12 and rep["names"]["AAA"]["pass"] is True
    assert rep["names"]["BBB"]["pass"] is False and rep["names"]["BBB"]["screened_on"] == rep["date"]
    assert rep["newly_noncompliant"] == [{"code": "BBB", "reason": "debt/mcap 31% >= 30%"}]
    assert json.loads((pkg / "live" / "controls.json").read_text())["excluded_symbols"] == ["BBB"]
