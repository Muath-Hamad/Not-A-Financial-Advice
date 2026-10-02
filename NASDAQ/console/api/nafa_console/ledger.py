"""Read the live ledger (NASDAQ/live/ledger) and the screen files into one
immutable snapshot. The ledger is the source of truth; the console only reads
it (docs/08 §2). A snapshot is rebuilt when any input file changes.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import Settings


def _load(p: Path, default: Any = None) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=20, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass(frozen=True)
class Commit:
    sha: str
    when: str  # ISO 8601 with offset
    subject: str


@dataclass
class Snapshot:
    """Everything the payload builders read. Built by `load_snapshot`."""

    twin: dict = field(default_factory=dict)
    cycles: dict[str, dict] = field(default_factory=dict)  # "2026-09-25-A" -> record
    gate: dict = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)  # asof -> orders file
    compliance: dict[str, dict] = field(default_factory=dict)  # date -> rescreen report
    controls: dict = field(default_factory=dict)
    halt: dict | None = None
    universe: dict = field(default_factory=dict)  # data/universe_screened.json
    fresh_screens: dict[str, dict] = field(default_factory=dict)  # date -> data/rescreen/<d>-screened.json
    overrides: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    head: Commit | None = None
    controls_log: list[Commit] = field(default_factory=list)
    previous_prices: dict[str, float] = field(default_factory=dict)  # symbol -> price at the previous twin asof
    fingerprint: str = ""

    # -- convenience ------------------------------------------------------
    def cycle_keys(self, kind: str) -> list[str]:
        return sorted(k for k in self.cycles if k.endswith("-" + kind))

    def latest_cycle(self, kind: str) -> dict | None:
        keys = self.cycle_keys(kind)
        return self.cycles[keys[-1]] if keys else None

    @property
    def universe_by_code(self) -> dict[str, dict]:
        return {u["code"]: u for u in self.universe.get("universe", [])}

    @property
    def latest_fresh_screen(self) -> tuple[str, dict] | None:
        if not self.fresh_screens:
            return None
        d = max(self.fresh_screens)
        return d, self.fresh_screens[d]


def _read_config(pkg: Path) -> dict:
    """The harness constants the console shows (live/config.py), parsed
    without importing the module, so the console never runs harness code."""
    src = (pkg / "live" / "config.py")
    out: dict = {}
    try:
        text = src.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    import ast

    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            try:
                out[name] = ast.literal_eval(node.value)
            except ValueError:
                if isinstance(node.value, ast.BoolOp):  # os.environ.get(...) or "default"
                    last = node.value.values[-1]
                    if isinstance(last, ast.Constant):
                        out[name] = last.value
    return out


def fingerprint(s: Settings) -> str:
    """Cheap change detector: newest mtime and file count of every input."""
    paths = [s.ledger_dir, s.pkg / "live" / "controls.json", s.pkg / "data" / "universe_screened.json",
             s.pkg / "data" / "sharia_overrides.json", s.pkg / "data" / "rescreen"]
    newest, count = 0.0, 0
    for p in paths:
        if not p.exists():
            continue
        files = [p] if p.is_file() else [f for f in p.rglob("*.json") if "smoke" not in f.parts]
        for f in files:
            st = f.stat()
            newest = max(newest, st.st_mtime)
            count += 1
    return f"{newest:.3f}:{count}"


def _previous_twin_prices(s: Settings, twin: dict) -> dict[str, float]:
    """Prices at the previous twin asof, from the git history of
    twin_latest.json (docs/08 §4: history backfilled from the git log)."""
    rel = (s.ledger_dir / "twin" / "twin_latest.json").resolve()
    try:
        rel_path = rel.relative_to(s.repo_root.resolve()).as_posix()
    except ValueError:
        return {}
    shas = git(s.repo_root, "log", "--format=%H", "-n", "12", "--", rel_path)
    if not shas:
        return {}
    for sha in shas.splitlines()[1:]:
        blob = git(s.repo_root, "show", f"{sha}:{rel_path}")
        if not blob:
            continue
        try:
            prev = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if prev.get("asof") and prev.get("asof") < twin.get("asof", ""):
            return {k: float(v.get("price") or 0) for k, v in (prev.get("positions") or {}).items()}
    return {}


def load_snapshot(s: Settings) -> Snapshot:
    L = s.ledger_dir
    snap = Snapshot()
    snap.twin = _load(L / "twin" / "twin_latest.json", {}) or {}
    for p in sorted((L / "cycles").glob("*.json")):
        rec = _load(p)
        if isinstance(rec, dict):
            snap.cycles[p.stem] = rec
    snap.gate = _load(L / "gate.json", {}) or {}
    for p in sorted((L / "orders").glob("*.json")):
        rec = _load(p)
        if isinstance(rec, dict):
            snap.orders[rec.get("asof") or p.stem] = rec
    for p in sorted((L / "compliance").glob("*.json")):
        rec = _load(p)
        if isinstance(rec, dict):
            snap.compliance[rec.get("date") or p.stem] = rec
    snap.halt = _load(L / "halt.json")
    snap.controls = _load(s.pkg / "live" / "controls.json", {}) or {}
    snap.universe = _load(s.pkg / "data" / "universe_screened.json", {}) or {}
    for p in sorted((s.pkg / "data" / "rescreen").glob("*-screened.json")):
        rec = _load(p)
        if isinstance(rec, dict):
            snap.fresh_screens[p.name[:10]] = rec
    snap.overrides = _load(s.pkg / "data" / "sharia_overrides.json", {}) or {}
    snap.config = _read_config(s.pkg)

    head = git(s.repo_root, "log", "-1", "--format=%H%x1f%cI%x1f%s")
    if head:
        sha, when, subj = head.split("\x1f", 2)
        snap.head = Commit(sha, when, subj)
    log = git(s.repo_root, "log", "-n", "50", "--format=%H%x1f%cI%x1f%s", "--", "NASDAQ/live/controls.json")
    if log:
        snap.controls_log = [Commit(*line.split("\x1f", 2)) for line in log.splitlines() if line.count("\x1f") == 2]
    snap.previous_prices = _previous_twin_prices(s, snap.twin) if snap.twin else {}
    snap.fingerprint = fingerprint(s)
    return snap
