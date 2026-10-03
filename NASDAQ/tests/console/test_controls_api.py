"""M1: authentication, the control pipeline (preview → step-up → validate →
commit → push → immediate command), the audit log and the preflight —
against a real temporary git repository. M2/M3: account book through a fake
gateway, performance, agent, the review pack and phone push."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pyotp
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from nafa_console.app import create_app  # noqa: E402
from nafa_console.auth import SESSION_COOKIE  # noqa: E402
from nafa_console.calendar import ET  # noqa: E402
from nafa_console.writer import GitWriter, WriteError  # noqa: E402

NOW = dt.datetime(2026, 10, 1, 18, 0, tzinfo=ET)
REASON = "testing the console write path"


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(pkg: Path) -> Path:
    root = pkg.parent
    sh(root, "init", "-q", "-b", "main")
    sh(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    sh(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    return root


class FakeDispatcher:
    configured = True

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def dispatch(self, workflow, inputs=None):
        if self.fail:
            raise WriteError("dispatch live-cycle-a.yml: HTTP 502")
        self.calls.append((workflow, inputs or {}))


@pytest.fixture
def make(settings, repo):
    def _make(auth=False, dispatcher=None, gateway=None, ntfy=None):
        app = create_app(settings, start_indexer=False, now=lambda: NOW, writer=GitWriter(repo, push=False),
                         dispatcher=dispatcher or FakeDispatcher(), gateway=gateway, auth_enabled=auth, ntfy=ntfy)
        return TestClient(app)
    return _make


def flow(cl, action, params=None, typed="", totp="123456", headers=None):
    pv = cl.post("/api/controls/preview", json={"action": action, "params": params or {}}, headers=headers or {})
    assert pv.status_code == 200, pv.text
    p = pv.json()
    r = cl.post("/api/controls/apply", json={"action": action, "params": params or {}, "reason": REASON, "category": "Test",
                                             "previewHash": p["previewHash"], "typed": typed or (p["word"] or ""), "totp": totp}, headers=headers or {})
    return p, r


# ───────── the control pipeline ─────────

def test_pause_entries_commits_with_a_structured_message(make, repo):
    with make() as cl:
        p, r = flow(cl, "pause")
        assert r.status_code == 200 and r.json()["applied"], r.text
        ctl = json.loads((repo / "NASDAQ/live/controls.json").read_text())
        assert ctl["pause_entries"] is True and ctl["version"] == 2
        msg = sh(repo, "log", "-1", "--format=%B")
        assert msg.startswith("control: pause_entries=true")
        assert f"Reason: [Test] {REASON}" in msg and "Actor: owner@console" in msg and "Console-Action-Id:" in msg
        rows = cl.get("/api/audit").json()["rows"]
        assert rows[0]["act"] == "pause_entries=true" and rows[0]["ba"] == "pause_entries: false → true" and rows[0]["res"] == "Applied"
        assert cl.get("/api/overview").json()["system"]["trading"] == "paused"


def test_effective_line_and_preview_rows(make):
    with make() as cl:
        p = cl.post("/api/controls/preview", json={"action": "pause", "params": {}}).json()
        assert p["eff"].startswith("Tonight’s 19:15 ET submit")
        assert p["rows"][0] == {"k": "controls.pause_entries", "a": "false", "b": "true"}
        assert p["steps"][:2] == ["Validated against the controls.json v2 schema", "Committed to the ledger"]


def test_a_stale_preview_is_refused_with_a_fresh_one(make, repo):
    with make() as cl:
        p = cl.post("/api/controls/preview", json={"action": "pause", "params": {}}).json()
        ctl = json.loads((repo / "NASDAQ/live/controls.json").read_text())
        ctl["gross_cap"] = 0.8                       # someone else committed in between
        (repo / "NASDAQ/live/controls.json").write_text(json.dumps(ctl, indent=2))
        sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "other change")
        r = cl.post("/api/controls/apply", json={"action": "pause", "params": {}, "reason": REASON, "category": "Test", "previewHash": p["previewHash"], "typed": ""})
        assert r.status_code == 409 and r.json()["preview"]["previewHash"] != p["previewHash"]


def test_destructive_actions_need_the_typed_word(make):
    with make() as cl:
        p = cl.post("/api/controls/preview", json={"action": "stop", "params": {}}).json()
        assert p["word"] == "STOP" and p["danger"]
        r = cl.post("/api/controls/apply", json={"action": "stop", "params": {}, "reason": REASON, "category": "Risk", "previewHash": p["previewHash"], "typed": "stp"})
        assert r.status_code == 400 and "Type STOP" in r.json()["detail"]


def test_stop_in_ghost_commits_kill_and_records_the_cancel(make, repo):
    with make() as cl:
        _, r = flow(cl, "stop")
        res = r.json()
        assert res["applied"] and any("Ghost: cancel all recorded" in s["l"] for s in res["steps"])
        assert json.loads((repo / "NASDAQ/live/controls.json").read_text())["kill"] is True
        assert cl.get("/api/overview").json()["system"]["trading"] == "stopped"


def test_validation_errors_block_the_write(make):
    with make() as cl:
        p = cl.post("/api/controls/preview", json={"action": "lock", "params": {"symbol": "ZZZ"}}).json()
        assert p["errors"] == ["ZZZ is not held"]
        _, r = flow(cl, "lock", {"symbol": "ZZZ"})
        assert r.status_code == 422


def test_lock_trim_and_cancel_manual(make, repo):
    with make() as cl:
        assert flow(cl, "lock", {"symbol": "AAA"})[1].json()["applied"]
        assert json.loads((repo / "NASDAQ/live/controls.json").read_text())["locked_symbols"] == ["AAA"]
        assert flow(cl, "unlock", {"symbol": "AAA"})[1].json()["applied"]
        p, r = flow(cl, "trim", {"symbol": "AAA", "pct": 25})
        assert r.json()["applied"] and p["word"] == "AAA"
        m = json.loads((repo / "NASDAQ/live/controls.json").read_text())["manual_orders"][0]
        assert (m["symbol"], m["side"], m["qty"], m["expires"]) == ("AAA", "sell", 30, "2026-10-01")
        assert flow(cl, "cancel_manual", {"id": m["id"]})[1].json()["applied"]
        assert json.loads((repo / "NASDAQ/live/controls.json").read_text())["manual_orders"] == []


def test_force_exit_excludes_and_shows_the_sale(make, repo):
    with make() as cl:
        p, r = flow(cl, "force_exit", {"symbol": "AAA"})
        assert p["added"][0]["s"] == "AAA" and p["added"][0]["q"] == "120 sh (all)"
        assert r.json()["applied"]
        assert "AAA" in json.loads((repo / "NASDAQ/live/controls.json").read_text())["excluded_symbols"]


def test_resume_needs_the_preflight(make):
    with make() as cl:
        flow(cl, "stop")
        for a in cl.get("/api/alerts").json()["alerts"]:
            if a["priority"] == "P1":
                cl.post(f"/api/alerts/{a['id']}/resolve", json={"note": "understood: vendor outage"})
        p = cl.post("/api/controls/preview", json={"action": "resume", "params": {}}).json()
        assert any("preflight" in e for e in p["errors"])
        pf = cl.post("/api/controls/preflight", json={"ticks": {"cyca": True, "ack": True}, "note": "data vendor fixed"}).json()
        assert {c["id"]: c["pass"] for c in pf["checks"]}["cyca"] is True
        _, r = flow(cl, "resume", {"ticks": {"cyca": True, "ack": True}, "note": "data vendor fixed"})
        assert r.json()["applied"], r.text


def test_clear_halt_writes_the_cause(make, repo):
    halt = repo / "NASDAQ/live/ledger/halt.json"
    halt.write_text(json.dumps({"halted": True, "since": "2026-09-30", "reason": "break", "diffs": [{"symbol": "AAA", "expected": 120, "actual": 119}]}))
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "halt")
    with make() as cl:
        cl.post("/api/sync")
        _, r = flow(cl, "clear_halt", {"cause": "broker delivered one share late; verified"})
        assert r.json()["applied"], r.text
        h = json.loads(halt.read_text())
        assert h["halted"] is False and h["cause"].startswith("broker delivered")


def test_rerun_dispatches_and_a_failed_dispatch_is_not_applied(make):
    d = FakeDispatcher()
    with make(dispatcher=d) as cl:
        assert flow(cl, "rerun", {"step": "Cycle A"})[1].json()["applied"]
        assert d.calls == [("live-cycle-a.yml", {})]
    with make(dispatcher=FakeDispatcher(fail=True)) as cl:
        res = flow(cl, "rerun", {"step": "Cycle A"})[1].json()
        assert res["applied"] is False and res["steps"][-1]["st"] == "fail"
        assert cl.get("/api/audit").json()["rows"][0]["res"] == "Not applied"


def test_release_needs_a_held_night(make):
    with make() as cl:
        assert "there is no held night to release" in cl.post("/api/controls/preview", json={"action": "release", "params": {}}).json()["errors"]


# ───────── authentication ─────────

def test_login_csrf_stepup_and_roles(make, settings):
    from nafa_console.store import Store
    auth = Store(settings.db_path).auth
    secret = auth.add_user("owner", "correct horse battery", "owner")
    vsecret = auth.add_user("viewer", "another long password", "viewer")
    totp = pyotp.TOTP(secret)
    with make(auth=True) as cl:
        assert cl.get("/api/overview").status_code == 401
        bad = cl.post("/api/auth/login", json={"username": "owner", "password": "wrong password!!", "code": totp.now()})
        assert bad.status_code == 401
        ok = cl.post("/api/auth/login", json={"username": "owner", "password": "correct horse battery", "code": totp.now()})
        assert ok.status_code == 200 and SESSION_COOKIE in ok.cookies
        csrf = ok.json()["csrf"]
        assert cl.get("/api/overview").status_code == 200
        # POST without the CSRF header is refused
        assert cl.post("/api/controls/preview", json={"action": "pause", "params": {}}).status_code == 403
        h = {"X-CSRF-Token": csrf}
        p = cl.post("/api/controls/preview", json={"action": "pause", "params": {}}, headers=h).json()
        # the login code was already used: replaying it fails the step-up
        body = {"action": "pause", "params": {}, "reason": REASON, "category": "Test", "previewHash": p["previewHash"], "typed": "", "totp": totp.now()}
        assert cl.post("/api/controls/apply", json=body, headers=h).status_code == 403
        next_code = totp.at(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30))
        r = cl.post("/api/controls/apply", json={**body, "totp": next_code}, headers=h)
        assert r.status_code == 200 and r.json()["applied"]
        assert cl.get("/api/audit").json()["logins"][0]["event"] == "stepup"
    with make(auth=True) as cl:
        v = cl.post("/api/auth/login", json={"username": "viewer", "password": "another long password", "code": pyotp.TOTP(vsecret).now()}).json()
        assert cl.post("/api/controls/preview", json={"action": "pause", "params": {}}, headers={"X-CSRF-Token": v["csrf"]}).status_code == 403
        assert cl.get("/api/holdings").status_code == 200


def test_five_failures_lock_the_account(make, settings):
    from nafa_console.store import Store
    Store(settings.db_path).auth.add_user("owner", "correct horse battery", "owner")
    with make(auth=True) as cl:
        for _ in range(5):
            cl.post("/api/auth/login", json={"username": "owner", "password": "nope nope nope", "code": "000000"})
        r = cl.post("/api/auth/login", json={"username": "owner", "password": "correct horse battery", "code": "000000"})
        assert r.status_code == 429


# ───────── M2: account through the gateway ─────────

class FakeGateway:
    latency_ms = 42

    def __init__(self, down=False):
        self.down = down
        self.commands = []

    def snapshot(self):
        from nafa_console.gateway import GatewayError
        if self.down:
            raise GatewayError("timeout")
        return {"account": {"status": "ACTIVE", "cash": "5000", "equity": "99000"},
                "positions": [{"symbol": "AAA", "qty": "118", "avg_entry_price": "10.2", "current_price": "12.0", "market_value": "1416", "unrealized_pl": "212"},
                              {"symbol": "XYZ", "qty": "3", "avg_entry_price": "5", "current_price": "5", "market_value": "15", "unrealized_pl": "0"}],
                "open_orders": []}

    def history(self):
        days = [dt.datetime(2026, 9, d, 16, tzinfo=ET) for d in (14, 15, 25)]
        return {"timestamp": [int(x.timestamp()) for x in days], "equity": [100000, 99700, 99000]}

    def command(self, action, **kw):
        self.commands.append(action)
        return {"status": "ok", "flatten": {"orders": [{"symbol": "AAA"}]} if action == "flatten" else None}


@pytest.fixture
def paper(repo):
    for rec in (repo / "NASDAQ/live/ledger/cycles").glob("*-A.json"):
        d = json.loads(rec.read_text())
        d["mode"] = "paper"
        rec.write_text(json.dumps(d))
    b = repo / "NASDAQ/live/ledger/cycles/2026-09-23-B.json"
    b.write_text(json.dumps({"cycle": "B", "asof": "2026-09-23", "status": "ok", "opens": {"AAA": 11.0},
                             "fills": [{"symbol": "AAA", "side": "buy", "qty": 20, "filled_qty": 18, "filled_avg_price": 11.011, "client_order_id": "x"}]}))
    return repo


def test_account_book_from_the_gateway(make, paper):
    g = FakeGateway()
    with make(gateway=g) as cl:
        o = cl.get("/api/overview").json()
        assert o["system"]["env"] == "paper" and o["accountCash"] == 5000.0
        assert o["system"]["facts"]["broker"]["reachable"] is True
        assert [p["account"] for p in o["equityCurve"]] == [100000, 99700, 99000]
        h = cl.get("/api/holdings").json()
        a = h["positions"][0]["account"]
        assert a["shares"] == 118 and a["avgCost"] == 10.2 and a["drift"]["row"].startswith("Account holds 118")
        assert h["accountOnly"] == [{"symbol": "XYZ", "shares": 3, "avgCost": 5.0, "last": 5.0}]
        newest = cl.get("/api/orders").json()["orders"][0]
        assert newest["accountShares"] == 18 and newest["fillPrice"] == 11.011 and newest["officialOpen"] == 11.0
        perf = cl.get("/api/performance").json()
        assert perf["execution"]["fills"][0]["bps"] == pytest.approx(10.0)
        _, r = flow(cl, "flatten")
        assert r.json()["applied"] and g.commands == ["flatten"]


def test_broker_unreachable_is_an_error_and_a_p1(make, paper):
    with make(gateway=FakeGateway(down=True)) as cl:
        assert cl.get("/api/overview").json()["system"]["health"] == "error"
        assert any(a["title"] == "Broker gateway unreachable" for a in cl.get("/api/alerts").json()["alerts"])


# ───────── M2/M3: performance, agent, review, push ─────────

def test_performance_agent_and_review(make):
    with make() as cl:
        perf = cl.get("/api/performance").json()
        keys = [m["key"] for m in perf["metrics"]]
        assert keys[:3] == ["total", "cagr", "sharpe"] and perf["metrics"][1]["model"] is None  # < 63 sessions
        assert perf["monthly"][0]["label"] == "Twin 2026"
        ag = cl.get("/api/agent").json()
        assert ag["handle"] == "trend" and "liveBands" in ag
        months = cl.get("/api/review").json()["months"]
        assert months == ["2026-09"]
        html = cl.get("/api/review/2026-09").text
        assert "Monthly review · 2026-09" in html and "BBB" in html


def test_new_p1_alerts_are_pushed_once(make):
    sent = []
    with make(ntfy=lambda t, b: sent.append(t)) as cl:
        cl.post("/api/sync")
        cl.post("/api/sync")
    assert sent and all(t.startswith("NAFA P1: ") for t in sent)
    assert len(sent) == len(set(sent))


def test_resolve_needs_a_note(make):
    with make() as cl:
        a = cl.get("/api/alerts").json()["alerts"][0]
        assert cl.post(f"/api/alerts/{a['id']}/resolve", json={"note": ""}).status_code == 400
        assert cl.post(f"/api/alerts/{a['id']}/resolve", json={"note": "vendor fixed the feed"}).status_code == 204
        a2 = next(x for x in cl.get("/api/alerts").json()["alerts"] if x["id"] == a["id"])
        assert a2["status"] == "resolved" and a2["note"] == "vendor fixed the feed"
