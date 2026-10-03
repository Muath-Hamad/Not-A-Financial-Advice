"""FastAPI app: the v1 API (docs/08 §10), authentication (§9), the control
service (§7), the indexer loop with phone push for new P1 alerts, and the
built web UI on the same port.

    uvicorn nafa_console.app:app --port 8080
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import analytics as A
from . import audit as AU
from . import calendar as cal
from . import control as C
from . import payloads as P
from .account import AccountSource
from .auth import SESSION_COOKIE, AuthError, Session
from .gateway import make_client
from .ledger import Snapshot, fingerprint, git, load_snapshot
from .settings import Settings
from .store import Store
from .writer import make_dispatcher, make_writer


class Indexer:
    """Keeps the newest ledger snapshot in memory. Every pass optionally pulls
    the ledger clone, then reloads only when an input file changed. Idempotent:
    a pass that finds nothing new records itself and keeps the snapshot."""

    def __init__(self, settings: Settings, store: Store, on_pass=None):
        self.settings = settings
        self.store = store
        self.on_pass = on_pass
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def snapshot(self) -> Snapshot:
        with self._lock:
            if self._snap is None:
                self._snap = load_snapshot(self.settings)
            return self._snap

    def run_once(self) -> bool:
        try:
            if self.settings.git_pull:
                if git(self.settings.repo_root, "pull", "--ff-only", "--quiet") is None:
                    raise RuntimeError("git pull --ff-only failed")
            fp = fingerprint(self.settings)
            changed = self._snap is None or fp != self._snap.fingerprint
            if changed:
                snap = load_snapshot(self.settings)
                with self._lock:
                    self._snap = snap
            head = self._snap.head.sha[:7] if self._snap and self._snap.head else None
            self.store.record_index(True, head, changed)
        except Exception as e:  # noqa: BLE001 — recorded; the last snapshot keeps serving
            self.store.record_index(False, None, False, str(e)[:300])
            changed = False
        if self.on_pass:
            try:
                self.on_pass()
            except Exception:  # noqa: BLE001 — a push failure must not stop indexing
                pass
        return changed

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.settings.index_every_s)

        threading.Thread(target=loop, name="indexer", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


def push_ntfy(url: str, title: str, body: str, priority: str = "high") -> None:
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Title": title.encode("ascii", "replace").decode(), "Priority": priority, "Tags": "rotating_light"})
    with urllib.request.urlopen(req, timeout=10):
        pass


def create_app(settings: Settings | None = None, *, start_indexer: bool = True, now=None, writer=None, dispatcher=None,
               gateway=None, auth_enabled: bool | None = None, ntfy=None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db_path)
    clock = now or (lambda: cal.now_et())
    writer = writer or make_writer(settings.repo_root)
    dispatcher = dispatcher or make_dispatcher()
    gw = gateway if gateway is not None else make_client()
    accounts = AccountSource(gw)
    auth_on = auth_enabled if auth_enabled is not None else os.environ.get("CONSOLE_AUTH", "on") != "off"
    ntfy_url = os.environ.get("CONSOLE_NTFY_URL")
    ntfy_send = ntfy or (lambda t, b: push_ntfy(ntfy_url, t, b)) if (ntfy or ntfy_url) else None
    holder: dict = {}

    def ctx() -> P.Ctx:
        snap = holder["indexer"].snapshot
        env_mode = ((snap.latest_cycle("A") or {}).get("mode") or "ghost")
        c = P.Ctx(snap, settings, clock(), store.indexer_status(), account=accounts.view() if env_mode != "ghost" else None)
        c.settings_store = store
        c.open_p1 = [a for a in P.alerts(c, store.alert_states())["alerts"] if a["priority"] == "P1" and a["status"] == "open"]
        return c

    def on_pass() -> None:
        if not ntfy_send:
            return
        c = ctx()
        for a in P.alerts(c, store.alert_states())["alerts"]:
            if a["priority"] == "P1" and a["status"] == "open" and store.mark_pushed(a["id"]):
                ntfy_send("NAFA P1: " + a["title"], a["detail"] + "\n" + a["source"])

    indexer = Indexer(settings, store, on_pass)
    holder["indexer"] = indexer

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        indexer.run_once()
        if start_indexer:
            indexer.start()
        yield
        indexer.stop()

    app = FastAPI(title="NAFA Console API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.indexer, app.state.store, app.state.settings = indexer, store, settings
    secure_cookie = os.environ.get("CONSOLE_SECURE_COOKIE", "0") == "1"

    # ───────── auth ─────────
    def session(request: Request) -> Session:
        if not auth_on:
            return Session(settings.user, settings.role, "", dt.datetime.now(dt.timezone.utc))
        s = store.auth.session(request.cookies.get(SESSION_COOKIE))
        if not s:
            raise HTTPException(401, "Sign in to continue.")
        if request.method == "POST" and request.headers.get("X-CSRF-Token") != s.csrf:
            raise HTTPException(403, "Missing or wrong CSRF token. Reload the page.")
        return s

    def owner(s: Session = Depends(session)) -> Session:
        if s.role != "owner":
            raise HTTPException(403, "Read-only viewer: controls are owner-only.")
        return s

    @app.exception_handler(AuthError)
    async def on_auth(_: Request, e: AuthError):
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.exception_handler(C.ControlError)
    async def on_control(_: Request, e: C.ControlError):
        return JSONResponse({"detail": e.message, "preview": e.preview}, status_code=e.status)

    @app.post("/api/auth/login")
    def login(body: dict, response: Response):
        if not auth_on:
            return {"user": settings.user, "role": settings.role, "csrf": "", "auth": False}
        if not store.auth.has_users():
            raise HTTPException(503, "No users yet. Run: python -m nafa_console.users add <name> --role owner")
        token, s = store.auth.login(str(body.get("username", "")), str(body.get("password", "")), str(body.get("code", "")))
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=secure_cookie, max_age=12 * 3600, path="/")
        return {"user": s.username, "role": s.role, "csrf": s.csrf, "auth": True}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        store.auth.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(s: Session = Depends(session)):
        age = int((dt.datetime.now(dt.timezone.utc) - s.totp_at).total_seconds()) if auth_on else None
        return {"user": s.username, "role": s.role, "csrf": s.csrf, "auth": auth_on, "totpAgeS": age}

    # ───────── reads ─────────
    def with_me(payload: dict, s: Session) -> dict:
        payload["me"] = {"user": s.username, "role": s.role}
        return payload

    @app.get("/healthz")
    def healthz():
        st = store.indexer_status()
        return {"ok": True, "version": __version__, "indexer_last_ok": (st.get("last_ok") or {}).get("at_utc"), "errors_24h": st.get("errors_24h", 0)}

    @app.get("/api/overview")
    def overview(s: Session = Depends(session)):
        return with_me(P.overview(ctx()), s)

    @app.get("/api/holdings")
    def holdings(book: str = "model", _: Session = Depends(session)):
        if book not in ("model", "account"):
            raise HTTPException(400, "book must be model or account")
        return P.holdings(ctx())

    @app.get("/api/holdings/{sym}")
    def holding(sym: str, _: Session = Depends(session)):
        d = P.holding_detail(ctx(), sym.upper())
        if d is None:
            raise HTTPException(404, f"{sym} is not held")
        return d

    @app.get("/api/orders/pending")
    def pending(_: Session = Depends(session)):
        return P.pending(ctx())

    @app.get("/api/orders")
    def orders(_: Session = Depends(session)):
        return P.history(ctx())

    @app.get("/api/round-trips")
    def round_trips(_: Session = Depends(session)):
        return P.round_trips(ctx())

    @app.get("/api/compliance")
    def compliance(_: Session = Depends(session)):
        return P.compliance(ctx())

    @app.get("/api/alerts")
    def alerts(_: Session = Depends(session)):
        return P.alerts(ctx(), store.alert_states())

    def _known_alert(alert_id: str) -> None:
        if alert_id not in {a["id"] for a in P.alerts(ctx(), store.alert_states())["alerts"]}:
            raise HTTPException(404, "unknown alert")

    @app.post("/api/alerts/{alert_id}/ack", status_code=204)
    def ack(alert_id: str, s: Session = Depends(owner)):
        _known_alert(alert_id)
        store.set_alert(alert_id, "acknowledged", s.username)

    @app.post("/api/alerts/{alert_id}/resolve", status_code=204)
    def resolve(alert_id: str, body: dict, s: Session = Depends(owner)):
        _known_alert(alert_id)
        note = str(body.get("note", "")).strip()
        if len(note) < 4:
            raise HTTPException(400, "A resolution note is required.")
        store.set_alert(alert_id, "resolved", s.username, note)

    @app.get("/api/health")
    def health(_: Session = Depends(session)):
        return P.health(ctx())

    @app.get("/api/roadmap")
    def roadmap(_: Session = Depends(session)):
        c = ctx()
        return P.roadmap(c, bool(c.open_p1))

    @app.get("/api/performance")
    def performance(_: Session = Depends(session)):
        return A.performance(ctx())

    @app.get("/api/agent")
    def agent(_: Session = Depends(session)):
        return A.agent(ctx())

    @app.get("/api/review")
    def review_list(_: Session = Depends(session)):
        return {"months": A.months(ctx())}

    @app.get("/api/review/{month}", response_class=HTMLResponse)
    def review(month: str, _: Session = Depends(session)):
        if len(month) != 7 or month[4] != "-":
            raise HTTPException(400, "month is YYYY-MM")
        c = ctx()
        rows = AU.entries(settings.repo_root, settings.ledger_dir, store)
        return HTMLResponse(A.review(c, month, rows, P.alerts(c, store.alert_states())["alerts"]))

    # ───────── controls (M1) ─────────
    @app.get("/api/controls")
    def controls(_: Session = Depends(session)):
        c = ctx()
        schema = C._schema(settings.pkg)
        return {"controls": schema.normalize(c.s.controls), "pending": AU.pending_changes(settings.repo_root, c.s.cycles),
                "write": writer.kind, "dispatch": dispatcher.configured, "gateway": gw is not None,
                "halt": c.s.halt, "heldNight": (c.s.cycles.get(f"{c.asof}-S") or {}).get("status") == "held",
                "exposure": round(sum(float(p.get("value") or 0) for p in c.positions.values()) / float(c.twin.get("equity_final") or 1) * 100, 1),
                "drawdown": round(((c.twin.get("equity") or [1])[-1] / max(c.twin.get("equity") or [1]) - 1) * 100, 1),
                "limits": {k: c.s.config.get(k) for k in ("MAX_POS_WEIGHT", "MAX_DAILY_TURNOVER", "ADV_CAP", "KILL_DD_LIMIT")}}

    @app.post("/api/controls/preflight")
    def preflight(body: dict, _: Session = Depends(owner)):
        return C.preflight(ctx(), body.get("ticks") or {}, body.get("note") or "")

    @app.post("/api/controls/preview")
    def preview(body: dict, _: Session = Depends(owner)):
        return C.preview(ctx(), writer, str(body.get("action")), body.get("params") or {})

    @app.post("/api/controls/apply")
    def apply(body: dict, request: Request, s: Session = Depends(owner)):
        if auth_on:
            store.auth.step_up(request.cookies.get(SESSION_COOKIE) or "", s, str(body.get("totp", "")))
        res = C.apply(ctx(), writer, dispatcher, gw, str(body.get("action")), body.get("params") or {}, actor=s.username,
                      reason=str(body.get("reason", "")), category=str(body.get("category", "")), preview_hash=str(body.get("previewHash", "")),
                      typed=str(body.get("typed", "")))
        if not auth_on:
            res["steps"].insert(0, {"l": "Step-up skipped: authentication is off (CONSOLE_AUTH=off, development)", "st": "skip"})
        indexer.run_once()
        return res

    @app.get("/api/audit")
    def audit(s: Session = Depends(session)):
        return {"rows": AU.entries(settings.repo_root, settings.ledger_dir, store),
                "logins": store.auth.events(100) if s.role == "owner" else []}

    @app.post("/api/sync", status_code=202)
    def sync(_: Session = Depends(session)):
        changed = indexer.run_once()
        return {"changed": changed, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    @app.exception_handler(Exception)
    async def on_error(_: Request, e: Exception):
        return JSONResponse({"detail": f"{type(e).__name__}: {e}"}, status_code=500)

    # The built SPA (web/dist): static assets, and index.html for client routes.
    static = settings.static_dir or (Path(__file__).resolve().parents[2] / "web" / "dist")
    if (static / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = static / path
            if path and f.is_file() and static in f.resolve().parents:
                return FileResponse(f)
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(static / "index.html")

    return app


app = create_app()
