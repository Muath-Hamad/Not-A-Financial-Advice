"""Shared fixtures for the live-harness tests.

The harness modules import each other by bare name (config, broker, ...), as
they do when run as scripts, so the tests put live/ and pipeline/ on the path.
Nothing here touches the network, the real ledger or a real broker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
for sub in ("live", "pipeline"):
    p = str(PKG / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

ASOF = "2026-09-28"  # a Monday session; its submit window opens 19:00 ET that evening


class FakeBroker:
    """Stands in for AlpacaPaperBroker: records what reaches the venue."""

    mode = "paper"

    def __init__(self, cash=20_000.0, equity=100_000.0, positions=None, reject=None,
                 duplicate=None, orders=None):
        self.cash, self.equity = cash, equity
        self._positions = positions or {}
        self.reject = reject or {}          # symbol -> (status, body)
        self.duplicate = duplicate or set()  # symbols already accepted earlier
        self.orders = orders or {}          # client_order_id -> order dict
        self.sent = []

    def account(self):
        return {"status": "ACTIVE", "cash": str(self.cash), "equity": str(self.equity),
                "buying_power": str(self.cash * 2), "trading_blocked": False,
                "account_blocked": False, "multiplier": "2"}

    def positions(self):
        return [{"symbol": s, "qty": str(q)} for s, q in self._positions.items()]

    def submit_moo(self, symbol, side, qty, coid):
        from broker import BrokerError
        if symbol in self.reject:
            raise BrokerError(*self.reject[symbol])
        if symbol in self.duplicate:
            raise BrokerError(422, '{"message":"client_order_id must be unique"}')
        self.sent.append({"symbol": symbol, "side": side, "qty": qty, "coid": coid})
        order = {"id": f"alp-{len(self.sent)}", "status": "accepted", "client_order_id": coid}
        self.orders[coid] = order
        return order

    def order_by_client_id(self, coid):
        return self.orders.get(coid)


class Alerts(list):
    def __call__(self, level, title, body="", dedupe=True):
        self.append((level, title, body))

    def levels(self):
        return [a[0] for a in self]


@pytest.fixture
def alerts():
    return Alerts()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


@pytest.fixture
def ledger(tmp_path):
    """A one-night ledger: Cycle A decided at ASOF, the twin holds AAA and BBB.

    Orders for the next open: sell all AAA, buy CCC (60 shares at ~$100),
    and a buy of DDD that a guardrail blocked.
    """
    from broker import client_order_id

    root = tmp_path / "ledger"
    write_json(root / "cycles" / f"{ASOF}-A.json",
               {"cycle": "A", "asof": ASOF, "status": "ok", "mode": "paper"})
    twin = {"asof": ASOF, "cash_final": 10_000.0, "equity_final": 100_000.0,
            "positions": {"AAA": {"shares": 100, "price": 50.0, "value": 5_000.0},
                          "BBB": {"shares": 200, "price": 425.0, "value": 85_000.0}},
            "orders_next_open": []}
    write_json(root / "twin" / "twin_latest.json", twin)
    raw = [{"code": "AAA", "side": "sell", "all": True},
           {"code": "CCC", "side": "buy", "sar": 6_000.0},
           {"code": "DDD", "side": "buy", "sar": 5_000.0}]
    entries = []
    for od in raw:
        close = {"AAA": 50.0, "CCC": 100.0, "DDD": 20.0}[od["code"]]
        qty = int(od["sar"] / (close * 1.0005)) if od["side"] == "buy" else 100
        entries.append({**od, "client_order_id": client_order_id(ASOF, od), "ref_close": close,
                        "share_preview": {"symbol": od["code"], "side": od["side"], "qty": qty},
                        "blocked": ["adv_cap"] if od["code"] == "DDD" else []})
    write_json(root / "orders" / f"{ASOF}.json", {"asof": ASOF, "orders": entries})
    return root


@pytest.fixture
def controls_dir(tmp_path):
    d = tmp_path / "live"
    write_json(d / "controls.json", {"kill": False, "pause_entries": False,
                                     "excluded_symbols": [], "gross_cap": None})
    return d
