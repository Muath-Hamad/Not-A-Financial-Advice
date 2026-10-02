"""Fixtures for the console API tests: a small synthetic ledger in a temp dir.

Nothing here touches the network, the real ledger or a broker. The package
under test lives in NASDAQ/console/api.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
API = PKG / "console" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))



def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1), encoding="utf-8")


def gate_checks(coverage: float) -> dict:
    return {
        "ixic_at_asof": {"pass": True, "last": "x"},
        "fetch_ok": {"pass": True, "value": 0.97, "min": 0.9},
        "coverage_at_asof": {"pass": coverage >= 0.95, "value": coverage, "min": 0.95, "missing": ["AAA", "BBB"] if coverage < 0.95 else []},
        "cross_source": {"pass": True, "compared": 1, "unavailable": 39, "disagreements": [], "tol": 0.005},
    }


@pytest.fixture
def pkg(tmp_path: Path) -> Path:
    """NASDAQ/-shaped tree: live/ledger, live/controls.json, data/*."""
    root = tmp_path / "NASDAQ"
    L = root / "live" / "ledger"
    trades = [
        {"date": "2026-09-14", "code": "AAA", "side": "buy", "shares": 100, "price": 10.005, "value": 1000.5, "fee": 0.0, "reason": "rank 1 momentum, 2% off the 52w high, ATR 3.0% -> 12% line"},
        {"date": "2026-09-15", "code": "BBB", "side": "buy", "shares": 50, "price": 40.02, "value": 2001.0, "fee": 0.0, "reason": "rank 2 momentum, 0% off the 52w high, ATR 4.0% -> 10% line"},
        {"date": "2026-09-22", "code": "BBB", "side": "sell", "shares": 50, "price": 35.982, "value": 1799.1, "fee": 0.0, "realized_pnl": -201.9, "held_since": "2026-09-15", "reason": "initial stop: 36.10 through 36.00 (3.0 ATR)"},
        {"date": "2026-09-23", "code": "AAA", "side": "buy", "shares": 20, "price": 11.0055, "value": 220.11, "fee": 0.0, "reason": "reload"},
    ]
    write(L / "twin" / "twin_latest.json", {
        "agent": "trend", "live_start": "2026-09-14", "asof": "2026-09-25", "sessions": 10,
        "dates": ["2026-09-14", "2026-09-15", "2026-09-25"], "equity": [100000.0, 99800.0, 99500.0],
        "cash": [100000.0, 97000.0, 98000.0], "bench": [100000.0, 100100.0, 100400.0],
        "positions": {"AAA": {"shares": 120, "price": 12.0, "value": 1440.0, "avg_cost": 10.1716, "weight": 0.0145, "unrealized_pct": 0.18}},
        "cash_final": 98060.0, "equity_final": 99500.0, "trades": trades, "commissions_paid": 0.0,
        "journal": [{"date": "2026-09-15", "mood": "trending", "sentiment": 0.4, "note": "Book now 3% invested."}],
        "adaptations": [], "inputs": {"slippage": "0.0005"},
    })
    write(L / "cycles" / "2026-09-25-A.json", {"cycle": "A", "asof": "2026-09-25", "mode": "ghost", "status": "ok", "ts_utc": "2026-09-25T21:05:41+00:00", "duration_s": 41.0,
                                              "data_gate": {"status": "pass", "checks": gate_checks(1.0)}, "determinism": {"match": True, "sha256": "94678b8da5e16f53"},
                                              "ghost_gate": {"streak": 1, "target": 10, "passed": False}})
    for d in ("2026-09-28", "2026-09-29"):
        write(L / "cycles" / f"{d}-A.json", {"cycle": "A", "asof": d, "mode": "ghost", "status": "data_gate_tripped", "ts_utc": f"{d}T21:30:00+00:00",
                                             "data_gate": {"status": "trip", "checks": gate_checks(0.0063)}})
        write(L / "cycles" / f"{d}-B.json", {"cycle": "B", "asof": d, "status": "no_orders_ledgered", "ts_utc": f"{d}T13:51:00+00:00"})
    write(L / "gate.json", {"streak": 1, "target": 10, "passed": False, "history": [{"asof": "2026-09-25", "hash8": "94678b8d", "match": True}]})
    write(L / "orders" / "2026-09-25.json", {"asof": "2026-09-25", "mode": "ghost", "orders": [
        {"code": "CCC", "side": "buy", "sar": 2500.0, "reason": "rank 3 momentum -> 9% line", "client_order_id": "nafa-2026-09-25-CCC-buy-1", "ref_close": 25.0, "share_preview": {"qty": 100}, "blocked": ["adv_cap"]},
    ]})
    write(L / "compliance" / "2026-10-01.json", {"date": "2026-10-01", "newly_noncompliant": [{"code": "DDD", "reason": "?"}], "newly_eligible": ["EEE"], "held_and_flagged": [], "policy": "excluded via controls.json"})
    write(root / "live" / "controls.json", {"kill": False, "pause_entries": False, "excluded_symbols": ["DDD"], "gross_cap": None})
    def u(code, debt, cash, flags=()):
        return {"code": code, "name": f"{code} Corp Common Stock", "sector": "Technology", "industry": "Software", "debt_ratio": debt, "cash_ratio": cash, "review_flags": list(flags), "pass": True}
    write(root / "data" / "universe_screened.json", {"universe": [u("AAA", 0.05, 0.04, ["streaming entertainment platform"]), u("BBB", 0.22, 0.05), u("CCC", 0.285, 0.01), u("DDD", 0.31, 0.02)],
                                                     "corrections": [{"date": "2026-09-25", "rule_layers": "instrument screen", "removed": [{"code": "ZZZP", "reasons": ["preferred shares"]}]}]})
    write(root / "data" / "rescreen" / "2026-10-01-screened.json", {"universe": [u("AAA", 0.06, 0.04, ["streaming entertainment platform"]), u("BBB", 0.22, 0.05), u("CCC", 0.285, 0.01)],
                                                                    "rejected_detail": [{**u("DDD", 0.31, 0.02), "ratio_reasons": ["debt/mcap 31% >= 30%"], "business_reasons": [], "instrument_reasons": [], "override_reasons": []}]})
    write(root / "data" / "sharia_overrides.json", {"review": {"AAA": "streaming entertainment platform"}})
    (root / "live" / "config.py").write_text('LIVE_START = os.environ.get("LIVE_START") or "2026-09-14"\nTWIN_SLIPPAGE = "0.0005"\nSTART_CASH = 100_000.0\n', encoding="utf-8")
    return root


@pytest.fixture
def settings(pkg: Path, tmp_path: Path):
    from nafa_console.settings import Settings
    return Settings(pkg=pkg, db_path=tmp_path / "console.db", static_dir=tmp_path / "no-static")

