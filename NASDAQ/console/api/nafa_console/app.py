"""FastAPI app: the v1 read API (docs/08 §10), the indexer loop, and the
built web UI served from the same port.

    uvicorn nafa_console.app:app --port 8080
"""

from __future__ import annotations

import datetime as dt
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import calendar as cal
from . import payloads as P
from .ledger import Snapshot, git, load_snapshot
from .settings import Settings
from .store import Store


class Indexer:
    """Keeps the newest ledger snapshot in memory. Every pass optionally pulls
    the ledger clone, then reloads only when an input file changed. Idempotent:
    a pass that finds nothing new records itself and keeps the snapshot."""

    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
            from .ledger import fingerprint
            fp = fingerprint(self.settings)
            changed = self._snap is None or fp != self._snap.fingerprint
            if changed:
                snap = load_snapshot(self.settings)
                with self._lock:
                    self._snap = snap
            head = self._snap.head.sha[:7] if self._snap and self._snap.head else None
            self.store.record_index(True, head, changed)
            return changed
        except Exception as e:  # noqa: BLE001 — any failure is recorded, the last snapshot keeps serving
            self.store.record_index(False, None, False, str(e)[:300])
            return False

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.settings.index_every_s)

        self._thread = threading.Thread(target=loop, name="indexer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def create_app(settings: Settings | None = None, *, start_indexer: bool = True, now=None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db_path)
    indexer = Indexer(settings, store)
    clock = now or (lambda: cal.now_et())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        indexer.run_once()
        if start_indexer:
            indexer.start()
        yield
        indexer.stop()

    app = FastAPI(title="NAFA Console API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.indexer = indexer
    app.state.store = store
    app.state.settings = settings

    def ctx() -> P.Ctx:
        return P.Ctx(indexer.snapshot, settings, clock(), store.indexer_status())

    @app.get("/healthz")
    def healthz():
        st = store.indexer_status()
        last_ok = (st.get("last_ok") or {}).get("at_utc")
        return {"ok": True, "version": __version__, "indexer_last_ok": last_ok, "errors_24h": st.get("errors_24h", 0)}

    @app.get("/api/overview")
    def overview():
        return P.overview(ctx())

    @app.get("/api/holdings")
    def holdings(book: str = "model"):
        if book not in ("model", "account"):
            raise HTTPException(400, "book must be model or account")
        return P.holdings(ctx())

    @app.get("/api/holdings/{sym}")
    def holding(sym: str):
        d = P.holding_detail(ctx(), sym.upper())
        if d is None:
            raise HTTPException(404, f"{sym} is not held")
        return d

    @app.get("/api/orders/pending")
    def pending():
        return P.pending(ctx())

    @app.get("/api/orders")
    def orders():
        return P.history(ctx())

    @app.get("/api/round-trips")
    def round_trips():
        return P.round_trips(ctx())

    @app.get("/api/compliance")
    def compliance():
        return P.compliance(ctx())

    @app.get("/api/alerts")
    def alerts():
        return P.alerts(ctx(), store.alert_states())

    @app.post("/api/alerts/{alert_id}/ack", status_code=204)
    def ack(alert_id: str):
        known = {a["id"] for a in P.alerts(ctx(), store.alert_states())["alerts"]}
        if alert_id not in known:
            raise HTTPException(404, "unknown alert")
        store.set_alert(alert_id, "acknowledged", settings.user)

    @app.get("/api/health")
    def health():
        return P.health(ctx())

    @app.get("/api/roadmap")
    def roadmap():
        c = ctx()
        open_p1 = any(a["priority"] == "P1" and a["status"] == "open" for a in P.alerts(c, store.alert_states())["alerts"])
        return P.roadmap(c, open_p1)

    @app.post("/api/sync", status_code=202)
    def sync():
        """Manual "sync now": one indexer pass."""
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
