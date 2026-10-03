"""HTTP surface of the console API (docs/08 §10). Skipped where FastAPI is
not installed (the harness test job); the console workflow installs it."""

from __future__ import annotations

import datetime as dt
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from nafa_console.app import create_app  # noqa: E402
from nafa_console.calendar import ET  # noqa: E402

NOW = dt.datetime(2026, 10, 1, 18, 0, tzinfo=ET)


@pytest.fixture
def client(settings):
    app = create_app(settings, start_indexer=False, now=lambda: NOW, auth_enabled=False)
    with TestClient(app) as c:
        yield c


ENDPOINTS = ["/api/overview", "/api/holdings", "/api/orders/pending", "/api/orders", "/api/round-trips",
             "/api/compliance", "/api/alerts", "/api/health", "/api/roadmap", "/healthz"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_every_read_endpoint_answers(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text


def test_overview_matches_the_web_contract(client):
    o = client.get("/api/overview").json()
    assert set(o) >= {"system", "controls", "me", "asof", "twinStart", "startCapital", "equity", "cash", "accountCash", "equityCurve", "markers", "phase"}
    assert set(o["system"]) >= {"env", "health", "trading", "released", "haltCleared", "stopAt", "flatten", "clock", "facts"}
    assert o["me"]["role"] == "owner"


def test_holding_detail_and_unknown_symbol(client):
    d = client.get("/api/holdings/aaa").json()
    assert d["symbol"] == "AAA" and d["prices"] == [] and "not stored in the ledger" in d["pricesNote"]
    assert client.get("/api/holdings/NOPE").status_code == 404


def test_holding_detail_carries_the_oos_calibration(client, settings):
    assert client.get("/api/holdings/AAA").json()["calibration"] == []
    out = settings.pkg / "out"
    out.mkdir(exist_ok=True)
    (out / "confidence_calibration.json").write_text(json.dumps({"bands": [{"band": "high", "n": 10, "hit_rate": 0.5, "avg_return": 0.01, "trade_won_rate": 0.7}]}))
    assert client.get("/api/holdings/AAA").json()["calibration"] == [{"band": "high", "n": 10, "wonRate": 0.7}]


def test_acknowledging_an_alert_persists(client):
    first = client.get("/api/alerts").json()["alerts"][0]
    assert client.post(f"/api/alerts/{first['id']}/ack").status_code == 204
    again = client.get("/api/alerts").json()["alerts"][0]
    assert again["id"] == first["id"] and again["status"] == "acknowledged"
    assert client.post("/api/alerts/A-unknown/ack").status_code == 404


def test_sync_runs_one_indexer_pass(client):
    r = client.post("/api/sync")
    assert r.status_code == 202 and "changed" in r.json()
    assert client.get("/healthz").json()["indexer_last_ok"]


def test_bad_book_is_rejected(client):
    assert client.get("/api/holdings?book=nope").status_code == 400
