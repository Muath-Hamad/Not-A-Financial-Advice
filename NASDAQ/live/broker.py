"""Broker abstraction (docs/05 §2): the agent never talks to a venue directly.

Two implementations behind one interface:

* GhostBroker — Phase 1. Orders are logged, never submitted; fills are the sim
  twin's own modeled fills. Exists so the whole cycle machinery (order
  translation, client-order-ids, reconciliation records) runs for real before
  a single order reaches a venue.

* AlpacaPaperBroker — Phase 2, dormant until APCA_* secrets exist. Speaks
  Alpaca's paper REST API; submits market-on-open (OPG) orders, the mechanical
  twin of the engine's fill-at-next-open. UNTESTED against the real API until
  keys are configured — the ghost gate must be green before it is switched on.

Order translation note (a declared fidelity gap, docs/06): the engine sizes
buys at the next open, which does not exist yet when an OPG order must be
submitted; the harness estimates the share count from asof's close. The twin
keeps its own count; any resulting share difference is measured by Cycle B's
reconciliation, not hidden.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

LIVE = Path(__file__).resolve().parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402


def client_order_id(asof: str, od: dict) -> str:
    basis = f"{asof}|{od['code']}|{od['side']}|" + json.dumps(
        {k: od.get(k) for k in ("sar", "weight", "shares", "fraction", "all")}, sort_keys=True)
    return f"nafa-{asof}-{od['code']}-{od['side']}-{hashlib.sha256(basis.encode()).hexdigest()[:8]}"


def to_share_order(od: dict, equity: float, close: float | None,
                   held_shares: int) -> dict | None:
    """Engine order dict -> {symbol, side, qty} for a whole-share OPG order."""
    code, side = od["code"], od["side"]
    if side == "buy":
        if not close or close <= 0:
            return None
        slip = float(config.TWIN_SLIPPAGE)
        if od.get("sar") is not None:
            qty = int(float(od["sar"]) / (close * (1 + slip)))
        elif od.get("weight") is not None:
            qty = int(float(od["weight"]) * equity / (close * (1 + slip)))
        elif od.get("shares") is not None:
            qty = int(od["shares"])
        else:
            return None
    else:
        if od.get("all"):
            qty = held_shares
        elif od.get("fraction") is not None:
            qty = int(held_shares * max(0.0, min(1.0, float(od["fraction"]))))
        elif od.get("shares") is not None:
            qty = min(held_shares, int(od["shares"]))
        elif od.get("sar") is not None and close:
            qty = min(held_shares, int(float(od["sar"]) / close))
        else:
            qty = held_shares
    if qty < 1:
        return None
    return {"symbol": code, "side": side, "qty": qty}


class GhostBroker:
    """Logs instead of trading. The ledger written by cycle_a IS its record."""

    mode = "ghost"

    def submit_moo(self, symbol: str, side: str, qty: int, coid: str) -> dict:
        return {"status": "ghost-logged", "symbol": symbol, "side": side,
                "qty": qty, "client_order_id": coid}

    def account(self) -> dict:
        return {"mode": "ghost"}

    def positions(self) -> list:
        return []

    def fills(self, day: str) -> list:
        return []

    def cancel_all(self) -> dict:
        return {"status": "ghost-noop"}


class AlpacaPaperBroker:
    """Alpaca paper venue. Requires APCA_API_KEY_ID / APCA_API_SECRET_KEY."""

    mode = "paper"

    def __init__(self):
        self.key = os.environ.get("APCA_API_KEY_ID", "")
        self.secret = os.environ.get("APCA_API_SECRET_KEY", "")
        if not (self.key and self.secret):
            raise RuntimeError("Alpaca keys missing (APCA_API_KEY_ID / APCA_API_SECRET_KEY)")
        self.base = config.ALPACA_PAPER_BASE

    def _req(self, method: str, path: str, payload=None):
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={"APCA-API-KEY-ID": self.key,
                     "APCA-API-SECRET-KEY": self.secret,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return json.loads(body) if body else {}

    def submit_moo(self, symbol: str, side: str, qty: int, coid: str) -> dict:
        return self._req("POST", "/v2/orders", {
            "symbol": symbol, "side": side, "qty": str(qty),
            "type": "market", "time_in_force": "opg",
            "client_order_id": coid,
        })

    def account(self) -> dict:
        return self._req("GET", "/v2/account")

    def positions(self) -> list:
        return self._req("GET", "/v2/positions")

    def fills(self, day: str) -> list:
        return self._req("GET", f"/v2/account/activities/FILL?date={day}")

    def cancel_all(self) -> dict:
        return self._req("DELETE", "/v2/orders")


def get_broker():
    if os.environ.get("LIVE_MODE", "ghost") == "paper":
        return AlpacaPaperBroker()
    return GhostBroker()
