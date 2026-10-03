"""The Account book (docs/08 §4, M2): what the broker account holds, from
the gateway (live snapshot, portfolio history) and the ledger's Cycle B
records (fills traced to client order ids, official opens, slippage).

The snapshot is cached briefly so a page load does not fan out to the
broker; a failure keeps the last good snapshot and marks it unreachable.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass, field

from .gateway import GatewayClient, GatewayError
from .payloads import ET, et_hm

CACHE_S = 60


@dataclass
class AccountView:
    reachable: bool
    positions: dict = field(default_factory=dict)   # sym -> {shares, avg_cost, price, value, unrealized}
    cash: float | None = None
    equity: float | None = None
    open_orders: list = field(default_factory=list)
    history: dict = field(default_factory=dict)     # ISO date -> equity
    at: float | None = None                         # epoch of the snapshot
    latency_ms: int | None = None
    error: str | None = None
    status: str | None = None

    @property
    def at_label(self) -> str | None:
        return et_hm(dt.datetime.fromtimestamp(self.at, dt.timezone.utc)) if self.at else None


class AccountSource:
    def __init__(self, client: GatewayClient | None):
        self.client = client
        self._lock = threading.Lock()
        self._view: AccountView | None = None
        self._fetched = 0.0

    @property
    def configured(self) -> bool:
        return self.client is not None

    def view(self, force: bool = False) -> AccountView | None:
        if not self.client:
            return None
        with self._lock:
            if not force and self._view and time.time() - self._fetched < CACHE_S:
                return self._view
            try:
                snap = self.client.snapshot()
                try:
                    hist = self.client.history()
                except GatewayError:
                    hist = {}
                acct = snap.get("account") or {}
                pos = {}
                for p in snap.get("positions") or []:
                    q = int(float(p.get("qty") or 0))
                    if q:
                        pos[p["symbol"]] = {"shares": q, "avg_cost": float(p.get("avg_entry_price") or 0), "price": float(p.get("current_price") or 0),
                                            "value": float(p.get("market_value") or 0), "unrealized": float(p.get("unrealized_pl") or 0)}
                history = {}
                for ts, eq in zip(hist.get("timestamp") or [], hist.get("equity") or []):
                    if eq is not None:
                        history[dt.datetime.fromtimestamp(ts, ET).date().isoformat()] = float(eq)
                self._view = AccountView(True, pos, float(acct.get("cash") or 0), float(acct.get("equity") or 0), snap.get("open_orders") or [],
                                         history, time.time(), self.client.latency_ms, None, acct.get("status"))
            except GatewayError as e:
                prev = self._view
                self._view = AccountView(False, prev.positions if prev else {}, prev.cash if prev else None, prev.equity if prev else None,
                                         prev.open_orders if prev else [], prev.history if prev else {}, prev.at if prev else None, None, str(e))
            self._fetched = time.time()
            return self._view


def ledger_fills(cycles: dict) -> dict[tuple[str, str, str], dict]:
    """(fill date, symbol, side) -> {qty, price, open, slippage_bps} from Cycle B records."""
    out = {}
    for key, rec in cycles.items():
        if not key.endswith("-B"):
            continue
        day = rec.get("asof")
        opens = rec.get("opens") or {}
        for f in rec.get("fills") or []:
            if not f.get("filled_qty"):
                continue
            px, op = f.get("filled_avg_price"), opens.get(f["symbol"])
            sign = 1 if f["side"] == "buy" else -1
            out[(day, f["symbol"], f["side"])] = {"qty": int(f["filled_qty"]), "price": px, "open": op,
                                                  "slippage_bps": round(sign * (px / op - 1) * 1e4, 1) if px and op else None,
                                                  "client_order_id": f.get("client_order_id")}
    return out
