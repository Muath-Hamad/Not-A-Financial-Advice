"""The broker gateway (docs/08 §3.1, §9) and the console's client for it.

The gateway is the only process that holds broker keys. It exposes reads
(account, positions, open orders, fills, portfolio history, health) and two
immediate commands (cancel_all, flatten) — no arbitrary-order endpoint;
manual orders go through controls.json only. Every command is recorded in
ledger/commands/<ts>.json by the harness's own control_cmd.run().

Phases 2–3: runs inside nafa-console on 127.0.0.1:8081 with the paper keys
(the entrypoint gives the keys to this process only). Phase 4: the same app
runs in nafa-live. The console reaches it with CONSOLE_GATEWAY_URL and a
shared CONSOLE_GATEWAY_TOKEN.

    uvicorn nafa_console.gateway:app --host 127.0.0.1 --port 8081
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ALPACA = {"paper": "https://paper-api.alpaca.markets", "live": "https://api.alpaca.markets"}


# ───────── the console's client ─────────

class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, url: str, token: str, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.last_ok: float | None = None
        self.latency_ms: int | None = None
        self.last_error: str | None = None

    def _req(self, method: str, path: str, body: dict | None = None):
        t0 = time.monotonic()
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Gateway-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
            self.last_ok = time.time()
            self.latency_ms = int((time.monotonic() - t0) * 1000)
            self.last_error = None
            return json.loads(raw) if raw else {}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.last_error = str(e)[:200]
            raise GatewayError(self.last_error) from e

    def health(self) -> dict:
        return self._req("GET", "/health")

    def snapshot(self) -> dict:
        """account + positions + open orders in one round trip."""
        return self._req("GET", "/snapshot")

    def fills(self, after: str) -> list:
        return self._req("GET", "/fills?" + urllib.parse.urlencode({"after": after}))

    def history(self) -> dict:
        return self._req("GET", "/portfolio-history")

    def command(self, action: str, *, reason: str, actor: str, action_id: str) -> dict:
        return self._req("POST", f"/commands/{action}", {"reason": reason, "actor": actor, "action_id": action_id})


def make_client() -> GatewayClient | None:
    url = os.environ.get("CONSOLE_GATEWAY_URL")
    return GatewayClient(url, os.environ.get("CONSOLE_GATEWAY_TOKEN", "")) if url else None


# ───────── the gateway service ─────────

class Alpaca:
    def __init__(self, key: str, secret: str, mode: str = "paper"):
        self.key, self.secret, self.mode = key, secret, mode
        self.base = ALPACA[mode]

    def req(self, method: str, path: str, payload=None):
        r = urllib.request.Request(self.base + path, method=method, data=json.dumps(payload).encode() if payload is not None else None,
                                   headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret, "Content-Type": "application/json"})
        with urllib.request.urlopen(r, timeout=20) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}


def create_gateway(alpaca: Alpaca | None = None, token: str | None = None, ledger: Path | None = None, pkg: Path | None = None):
    from fastapi import FastAPI, Header, HTTPException

    token = token if token is not None else os.environ.get("CONSOLE_GATEWAY_TOKEN", "")
    mode = os.environ.get("GATEWAY_MODE", "paper")
    if alpaca is None:
        key, secret = os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
        alpaca = Alpaca(key, secret, mode) if key and secret else None
    pkg = pkg or Path(os.environ.get("CONSOLE_PKG_DIR") or Path(__file__).resolve().parents[3])
    ledger = ledger or Path(os.environ.get("LIVE_LEDGER_DIR") or pkg / "live" / "ledger")
    app = FastAPI(title="NAFA broker gateway", docs_url=None, redoc_url=None, openapi_url=None)

    def guard(x_gateway_token: str | None):
        if not token or x_gateway_token != token:
            raise HTTPException(401, "bad gateway token")
        if alpaca is None:
            raise HTTPException(503, "no broker keys configured")

    @app.get("/health")
    def health(x_gateway_token: str | None = Header(default=None)):
        guard(x_gateway_token)
        t0 = time.monotonic()
        acct = alpaca.req("GET", "/v2/account")
        return {"ok": True, "mode": alpaca.mode, "status": acct.get("status"), "latency_ms": int((time.monotonic() - t0) * 1000)}

    @app.get("/snapshot")
    def snapshot(x_gateway_token: str | None = Header(default=None)):
        guard(x_gateway_token)
        acct = alpaca.req("GET", "/v2/account")
        return {"mode": alpaca.mode, "at": time.time(),
                "account": {k: acct.get(k) for k in ("status", "cash", "equity", "last_equity", "buying_power", "trading_blocked", "account_blocked", "multiplier", "pattern_day_trader")},
                "positions": alpaca.req("GET", "/v2/positions"),
                "open_orders": alpaca.req("GET", "/v2/orders?status=open&limit=500")}

    @app.get("/fills")
    def fills(after: str, x_gateway_token: str | None = Header(default=None)):
        guard(x_gateway_token)
        out, page = [], None
        for _ in range(20):
            q = {"after": after, "direction": "asc", "page_size": 100}
            if page:
                q["page_token"] = page
            batch = alpaca.req("GET", "/v2/account/activities/FILL?" + urllib.parse.urlencode(q))
            out += batch
            if len(batch) < 100:
                break
            page = batch[-1].get("id")
        return out

    @app.get("/portfolio-history")
    def history(x_gateway_token: str | None = Header(default=None)):
        guard(x_gateway_token)
        return alpaca.req("GET", "/v2/account/portfolio/history?period=1A&timeframe=1D")

    @app.post("/commands/{action}")
    def command(action: str, body: dict, x_gateway_token: str | None = Header(default=None)):
        guard(x_gateway_token)
        if action not in ("cancel_all", "flatten"):
            raise HTTPException(404, "unknown command")
        live = str(pkg / "live")
        if live not in sys.path:
            sys.path.insert(0, live)
        import control_cmd  # the harness's own recorder
        from broker import BrokerError  # noqa: F401

        class _B:  # adapter: the harness broker interface over this gateway's keys
            mode = alpaca.mode

            def cancel_all(self):
                res = alpaca.req("DELETE", "/v2/orders")
                return {"status": "ok", "canceled": res if isinstance(res, list) else []}

            def flatten(self, day):
                orders = []
                for p in alpaca.req("GET", "/v2/positions"):
                    qty = int(float(p.get("qty") or 0))
                    if qty < 1:
                        continue
                    coid = f"nafa-{day}-{p['symbol']}-sell-flatten"
                    try:
                        r = alpaca.req("POST", "/v2/orders", {"symbol": p["symbol"], "side": "sell", "qty": str(qty), "type": "market",
                                                              "time_in_force": "opg", "client_order_id": coid})
                        orders.append({"symbol": p["symbol"], "qty": qty, "client_order_id": coid, "status": r.get("status"), "id": r.get("id")})
                    except urllib.error.HTTPError as e:
                        orders.append({"symbol": p["symbol"], "qty": qty, "client_order_id": coid, "error": f"HTTP {e.code}"})
                return {"status": "ok" if all("error" not in o for o in orders) else "partial", "orders": orders}

        return control_cmd.run(action, body.get("reason", ""), body.get("actor", "owner@console"), body.get("action_id"), ledger, broker=_B())

    return app


try:  # the module-level app for uvicorn; the console process never imports it with keys
    app = create_gateway()
except Exception:  # noqa: BLE001 - FastAPI missing in a tooling context
    app = None
