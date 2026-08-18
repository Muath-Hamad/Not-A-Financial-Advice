"""Cycle A — the post-close decision cycle (docs/05 §3).

Fetch the day's completed bars, gate the data, replay the sim twin twice
(the determinism gate), check guardrails, ledger today's orders for
tomorrow's open, and rebuild the cockpit. Every run leaves a cycle record;
the workflow commits whatever was written, so the repo stays the audit log
even for failed cycles.

Exit code 0 means "a record was written" (including gate trips and kill
switches — those are outcomes, not errors). Only an unexpected crash exits
non-zero.

Usage:
  python NASDAQ/live/cycle_a.py            # the real thing (runner)
  python NASDAQ/live/cycle_a.py --smoke    # full mechanics, ledger/smoke/, no alerts
  python NASDAQ/live/cycle_a.py --local    # no fetch/enrich; TWIN_* env picks data
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LIVE = Path(__file__).resolve().parent
PKG = LIVE.parent
sys.path.insert(0, str(LIVE))

import config  # noqa: E402
from alert import alert, step_summary  # noqa: E402
from broker import client_order_id, get_broker, to_share_order  # noqa: E402
from guardrails import check_orders  # noqa: E402


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PKG, timeout=15,
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))


def run_pipeline(script: str, env_extra: dict) -> int:
    env = {**os.environ, **env_extra}
    return subprocess.run([sys.executable, str(PKG / "pipeline" / script)],
                          env=env, cwd=PKG).returncode


def run_twin(out_path: Path) -> int:
    return subprocess.run([sys.executable, str(LIVE / "twin.py"), "--out", str(out_path)],
                          cwd=PKG).returncode


def enriched_refs(codes: list[str], asof: str) -> dict:
    """{code: {close, adv_dollars}} at asof, from the enriched files."""
    refs = {}
    enriched = PKG / os.environ.get("TWIN_ENRICHED_SUBDIR", config.ENRICHED_SUBDIR)
    for code in codes:
        path = enriched / f"{code}.csv"
        if not path.exists():
            continue
        try:
            header, row = None, None
            with open(path) as f:
                header = f.readline().strip().split(",")
                for line in f:
                    parts = line.rstrip("\n").split(",")
                    if parts[0] == asof:
                        row = parts
                        break
            if row is None:
                continue
            g = dict(zip(header, row))
            close = float(g.get("Close") or 0) or None
            vol20 = float(g.get("vol_sma20") or 0) or None
            refs[code] = {"close": close,
                          "adv_dollars": (vol20 * close) if (vol20 and close) else None}
        except Exception:  # noqa: BLE001 - a missing ref only weakens one check
            continue
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="full mechanics into ledger/smoke/, no alerts, no streak")
    ap.add_argument("--local", action="store_true",
                    help="skip fetch/enrich; TWIN_* env points at existing data")
    args = ap.parse_args()
    if args.smoke:
        os.environ["LIVE_SMOKE"] = "1"

    ledger = config.LEDGER / "smoke" if args.smoke else config.LEDGER
    t0 = dt.datetime.now(dt.timezone.utc)
    record: dict = {"cycle": "A", "ts_utc": utcnow(), "mode": os.environ.get("LIVE_MODE", "ghost"),
                    "smoke": bool(args.smoke), "code_version": git_head()}

    # ---- which session is this cycle for? --------------------------------
    if args.local:
        asof = None  # resolved from the twin output below
    else:
        from calendar_util import latest_completed_session, next_session, now_et
        # The crons fire at 21:00 and 22:00 UTC so one of them is 17:00 ET in
        # either DST regime; skip any slot that lands before 16:45 ET (closing
        # prints settle in the first minutes after the bell). No upper bound —
        # a late manual re-run is always allowed.
        if not args.smoke:
            now = now_et()
            if now.hour * 60 + now.minute < 16 * 60 + 45:
                print(f"{now:%H:%M} ET is before the 16:45 ET window; "
                      f"the later cron slot will run this cycle")
                return 0
        asof = latest_completed_session()
        record["asof"] = asof
        if (ledger / "cycles" / f"{asof}-A.json").exists():
            print(f"cycle A for {asof} already recorded; nothing to do")
            return 0

    # ---- controls / kill switch ------------------------------------------
    controls = json.loads((LIVE / "controls.json").read_text())
    record["controls"] = {k: controls.get(k) for k in
                          ("kill", "pause_entries", "excluded_symbols", "gross_cap")}
    if controls.get("kill"):
        record["status"] = "killed"
        write_json(ledger / "cycles" / f"{asof or 'unknown'}-A.json", record)
        alert("P1", "Kill switch is on — cycle held",
              f"controls.json has kill=true; no data fetched, no orders for {asof}.")
        return 0

    # ---- fetch + enrich ---------------------------------------------------
    if not args.local:
        rc = run_pipeline("fetch_data.py", {
            "FETCH_START": config.FETCH_START,
            "FETCH_RAW_SUBDIR": config.RAW_SUBDIR,
            "FETCH_MIN_OK": "0.90",
        })
        if rc != 0:
            record["status"] = "fetch_failed"
            write_json(ledger / "cycles" / f"{asof}-A.json", record)
            alert("P1", f"Cycle A {asof}: data fetch failed",
                  "fetch_data.py exited non-zero; no orders will be issued. "
                  "See the workflow log.")
            return 0
        rc = run_pipeline("indicators.py", {
            "IND_RAW_SUBDIR": config.RAW_SUBDIR,
            "IND_OUT_SUBDIR": config.ENRICHED_SUBDIR,
            "IND_LAST_DATE": asof,
        })
        if rc != 0:
            record["status"] = "enrich_failed"
            write_json(ledger / "cycles" / f"{asof}-A.json", record)
            alert("P1", f"Cycle A {asof}: indicator build failed",
                  "indicators.py exited non-zero; no orders will be issued.")
            return 0

        # ---- data gate ----------------------------------------------------
        from data_gate import run_gate
        prev_state_path = ledger / "twin" / "twin_latest.json"
        priority: list[str] = []
        if prev_state_path.exists():
            prev_state = json.loads(prev_state_path.read_text())
            priority = list(prev_state.get("positions", {})) + \
                [o["code"] for o in prev_state.get("orders_next_open", [])]
        gate = run_gate(asof, priority)
        record["data_gate"] = gate
        if gate["status"] == "trip":
            record["status"] = "data_gate_tripped"
            write_json(ledger / "cycles" / f"{asof}-A.json", record)
            alert("P1", f"Cycle A {asof}: data gate tripped — no trading tomorrow",
                  "```json\n" + json.dumps(gate["checks"], indent=1)[:3000] + "\n```")
            return 0
        if gate["status"] == "degraded":
            alert("P2", f"Cycle A {asof}: second data source unavailable",
                  "Stooq cross-check could not compare any symbol; "
                  "trading continues on the primary source only.")

    # ---- the twin, twice (determinism gate) ------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="twin-"))
    twin_a, twin_b = tmp / "twin_run1.json", tmp / "twin_run2.json"
    for out_path in (twin_a, twin_b):
        rc = run_twin(out_path)
        if rc != 0:
            record["status"] = "twin_failed"
            write_json(ledger / "cycles" / f"{asof or 'unknown'}-A.json", record)
            alert("P1", f"Cycle A {asof}: twin replay failed",
                  "twin.py exited non-zero; no orders will be issued.")
            return 0
    ha, hb = sha256_file(twin_a), sha256_file(twin_b)
    twin = json.loads(twin_a.read_text())
    if asof is None:
        asof = twin["asof"]
        record["asof"] = asof
        if (ledger / "cycles" / f"{asof}-A.json").exists():
            print(f"cycle A for {asof} already recorded; nothing to do")
            return 0

    deterministic = ha == hb
    record["determinism"] = {"match": deterministic, "sha256": ha[:16]}

    # ghost-gate streak (real runs only)
    gate_path = ledger / "gate.json"
    if not args.smoke:
        g = json.loads(gate_path.read_text()) if gate_path.exists() else \
            {"streak": 0, "target": config.GATE_TARGET_STREAK, "passed": False, "history": []}
        if deterministic:
            g["streak"] += 1
        else:
            g["streak"] = 0
        g["passed"] = g["passed"] or g["streak"] >= g["target"]
        g["updated"] = asof
        g["history"] = (g["history"] + [{"asof": asof, "hash8": ha[:8],
                                         "match": deterministic}])[-30:]
        write_json(gate_path, g)
        record["ghost_gate"] = {"streak": g["streak"], "target": g["target"],
                                "passed": g["passed"]}
        if g["passed"] and g["streak"] == g["target"]:
            alert("P2", f"Ghost gate PASSED — {g['target']} consecutive deterministic sessions",
                  "Phase 1 exit criterion met (docs/05 §10). Phase 2 needs Alpaca "
                  "paper keys (APCA_API_KEY_ID / APCA_API_SECRET_KEY) and LIVE_MODE=paper.")

    if not deterministic:
        record["status"] = "nondeterministic"
        write_json(ledger / "cycles" / f"{asof}-A.json", record)
        alert("P1", f"Cycle A {asof}: twin replay is NONDETERMINISTIC",
              f"Two replays of the same snapshot produced different bytes "
              f"({ha[:12]} vs {hb[:12]}). Determinism is broken — no orders. "
              f"This halts the ghost gate streak.")
        return 0

    # ---- auto kill-switch check (drawdown beyond the declared hard limit) -
    eq = twin["equity"]
    dd = eq[-1] / max(eq) - 1 if eq else 0.0
    record["drawdown_from_peak"] = round(dd, 4)
    if dd <= config.KILL_DD_LIMIT:
        alert("P1", f"Drawdown {dd:.1%} beyond the declared kill limit "
                    f"{config.KILL_DD_LIMIT:.0%}",
              "docs/05 §7.1: in paper mode the harness stops submitting orders "
              "until a human clears controls.json. Ghost mode: recorded and alerted.")
        record["kill_triggered"] = True

    # ---- guardrails on today's orders ------------------------------------
    orders = twin["orders_next_open"]
    universe = {u["code"] for u in
                json.loads((PKG / "data" / "universe_screened.json").read_text())["universe"]}
    refs = enriched_refs([od["code"] for od in orders], asof)
    rails = check_orders(orders, twin, refs, universe, controls)
    record["guardrails"] = rails
    if rails["violations"]:
        alert("P2", f"Cycle A {asof}: {len(rails['violations'])} guardrail flag(s)",
              "```json\n" + json.dumps(rails["violations"], indent=1)[:3000] + "\n```"
              + ("\nGhost mode is report-only; the ledger mirrors the twin."
                 if record["mode"] == "ghost" else ""))

    # ---- open-revision check vs yesterday's Cycle B ----------------------
    if not args.local:
        try:
            b_path = ledger / "cycles" / f"{asof}-B.json"
            if b_path.exists():
                b_rec = json.loads(b_path.read_text())
                opens_0950 = b_rec.get("opens", {})
                slip = float(config.TWIN_SLIPPAGE)
                revs = []
                for t in twin["trades"]:
                    if t["date"] != asof or t["code"] not in opens_0950:
                        continue
                    open_evening = t["price"] / (1 + slip) if t["side"] == "buy" \
                        else t["price"] / (1 - slip)
                    o = opens_0950[t["code"]]
                    if o:
                        revs.append({"code": t["code"],
                                     "diff": round(abs(open_evening / o - 1), 5)})
                worst = max((r["diff"] for r in revs), default=0.0)
                record["open_revision"] = {"n": len(revs), "worst": worst}
                if worst > config.OPEN_REVISION_TOL:
                    alert("P2", f"Cycle A {asof}: open prices revised up to {worst:.2%} "
                                f"since 09:50", json.dumps(revs))
        except Exception as exc:  # noqa: BLE001 - a quality metric, never a blocker
            record["open_revision"] = {"error": str(exc)[:200]}

    # ---- ledger: orders, twin state, cycle record ------------------------
    order_entries = []
    for od in orders:
        coid = client_order_id(asof, od)
        held = twin["positions"].get(od["code"], {}).get("shares", 0)
        close = refs.get(od["code"], {}).get("close")
        share_od = to_share_order(od, twin["equity_final"], close, held)
        order_entries.append({**od, "client_order_id": coid,
                              "share_preview": share_od})
    write_json(ledger / "orders" / f"{asof}.json", {
        "asof": asof, "mode": record["mode"], "orders": order_entries,
        "generated_utc": record["ts_utc"],
    })

    # broker submission — a real venue only in paper mode, after the rails
    broker = get_broker()
    submitted = []
    if broker.mode == "paper" and not controls.get("kill") \
            and not record.get("kill_triggered"):
        blocked = {(v.get("code"), v.get("side")) for v in rails["violations"]}
        for e in order_entries:
            if (e["code"], e["side"]) in blocked or e["share_preview"] is None:
                continue
            try:
                submitted.append(broker.submit_moo(
                    e["share_preview"]["symbol"], e["side"],
                    e["share_preview"]["qty"], e["client_order_id"]))
            except Exception as exc:  # noqa: BLE001
                alert("P1", f"Order rejected: {e['code']} {e['side']}", str(exc)[:500])
    record["submitted"] = submitted

    twin_dir = ledger / "twin"
    twin_dir.mkdir(parents=True, exist_ok=True)
    (twin_dir / "twin_latest.json").write_text(json.dumps(twin))
    with open(twin_dir / "equity.csv", "w") as f:
        f.write("date,equity,cash,bench\n")
        for d, e, c, b in zip(twin["dates"], twin["equity"], twin["cash"], twin["bench"]):
            f.write(f"{d},{e},{c},{b}\n")

    record["status"] = "ok"
    record["twin"] = {
        "sessions": twin["sessions"], "equity_final": twin["equity_final"],
        "ret_total": round(twin["equity_final"] / config.START_CASH - 1, 4),
        "n_positions": len(twin["positions"]), "n_orders_next_open": len(orders),
        "n_trades": len(twin["trades"]), "n_adaptations": len(twin["adaptations"]),
        "decide_errors": twin["decide_errors"], "inputs": twin["inputs"],
    }
    record["duration_s"] = round((dt.datetime.now(dt.timezone.utc) - t0).total_seconds(), 1)
    write_json(ledger / "cycles" / f"{asof}-A.json", record)

    # ---- cockpit ----------------------------------------------------------
    cockpit_out = str(ledger / "cockpit.html") if args.smoke \
        else str(LIVE / "cockpit" / "index.html")
    rc = subprocess.run([sys.executable, str(LIVE / "cockpit" / "build_cockpit.py"),
                         "--ledger", str(ledger), "--out", cockpit_out],
                        cwd=PKG).returncode
    if rc != 0:
        alert("P2", f"Cycle A {asof}: cockpit build failed",
              "The cycle itself is fine; the dashboard did not update.")

    # ---- digest -----------------------------------------------------------
    nxt = "?" if args.local else next_session(asof)
    step_summary(
        f"### Cycle A — {asof}\n\n"
        f"| | |\n|---|---|\n"
        f"| twin equity | ${twin['equity_final']:,.2f} "
        f"({twin['equity_final'] / config.START_CASH - 1:+.2%}) |\n"
        f"| drawdown from peak | {dd:.2%} |\n"
        f"| positions | {len(twin['positions'])} |\n"
        f"| orders for {nxt} | {len(orders)} "
        f"(buys ${rails['buy_total']:,.0f} / sells ${rails['sell_total']:,.0f}) |\n"
        f"| guardrail flags | {len(rails['violations'])} |\n"
        f"| determinism | {'match' if deterministic else 'MISMATCH'} "
        f"(streak {record.get('ghost_gate', {}).get('streak', '—')}"
        f"/{config.GATE_TARGET_STREAK}) |\n"
        f"| data gate | {record.get('data_gate', {}).get('status', 'local')} |\n")
    print(f"cycle A {asof}: ok — equity {twin['equity_final']:,.2f}, "
          f"{len(orders)} orders, streak "
          f"{record.get('ghost_gate', {}).get('streak', '-')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort record + alert, then fail loud
        alert("P1", "Cycle A crashed", f"{type(exc).__name__}: {exc}"[:800])
        raise
